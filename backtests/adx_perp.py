"""ADX Adaptive + 永续合约：双向开仓 + 杠杆 + funding rate。

Long:  趋势突破买入 / RSI超卖做多
Short: 趋势跌破卖出 / RSI超买做空
"""

from __future__ import annotations

import logging, sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"

# 费用
FEE = 0.0004          # 永续 taker 0.04%
SLIPPAGE = 0.001      # 0.1% — 极端压力测试
FUNDING_RATE = 0.0000375  # 0.01%/8h → 0.00375%/4h bar

# 杠杆
MAX_LEVERAGE = 10.0

# ADX
ADX_PERIOD, ADX_TREND, ADX_RANGE = 14, 25, 20
DC_PERIOD, ATR_PERIOD = 20, 14
ATR_TRAIL_MULT = 2.5

# RSI
RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT = 14, 35, 65
MR_ATR_STOP_MULT = 3.5

# 风控
RISK_PER_TRADE = 0.04
CB_MAX_LOSSES, CB_COOLDOWN = 5, 24
LIQ_THRESHOLD = 0.90  # 亏 90% 保证金 → 强平


def entry_cost(price: float) -> float:
    return price * (1 + SLIPPAGE) * (1 + FEE)

def exit_value(price: float) -> float:
    return price * (1 - SLIPPAGE) * (1 - FEE)


def load_data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l = df["close"], df["high"], df["low"]

    delta = c.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    df["rsi"] = 100 - 100/(1 + avg_gain/avg_loss.replace(0, np.nan))

    tr1, tr2, tr3 = h-l, (h-c.shift()).abs(), (l-c.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    up, down = h-h.shift(), l.shift()-l
    pdm = pd.Series(np.where((up>down)&(up>0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((down>up)&(down>0), down, 0.0), index=df.index)
    pdi = 100*(pdm.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()/atr.replace(0,np.nan))
    ndi = 100*(ndm.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()/atr.replace(0,np.nan))
    dx = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    df["atr"] = tr.ewm(alpha=1/ATR_PERIOD, min_periods=ATR_PERIOD).mean()

    df["dc_high"] = h.rolling(DC_PERIOD).max()
    df["dc_low"] = l.rolling(DC_PERIOD).min()

    df["long_trend"] = c > df["dc_high"].shift(1)          # 突破做多
    df["short_trend"] = c < df["dc_low"]                    # 跌破做空
    df["long_mr"] = df["rsi"] < RSI_OVERSOLD                # 超卖做多
    df["short_mr"] = df["rsi"] > RSI_OVERBOUGHT             # 超买做空

    df["is_trend"] = df["adx"] > ADX_TREND
    df["is_range"] = df["adx"] < ADX_RANGE

    df["long_sig"] = (df["is_trend"] & df["long_trend"]) | (df["is_range"] & df["long_mr"])
    df["short_sig"] = (df["is_trend"] & df["short_trend"]) | (df["is_range"] & df["short_mr"])
    df["close_sig"] = df["is_range"] & (df["rsi"] > RSI_OVERBOUGHT)  # 震荡市平多
    df["cover_sig"] = df["is_range"] & (df["rsi"] < RSI_OVERSOLD)    # 震荡市平空
    df["close_trend"] = df["is_trend"] & df["short_trend"]
    df["cover_trend"] = df["is_trend"] & df["long_trend"]

    return df


def calc_contracts(equity: float, price: float, atr_val: float, leverage: float) -> float:
    """计算合约张数: 风险/笔固定，波动大→仓位小。"""
    if atr_val <= 0:
        atr_val = price * 0.02
    risk_amount = equity * RISK_PER_TRADE
    stop_dist = atr_val * ATR_TRAIL_MULT
    raw_value = risk_amount / (stop_dist / price)  # position notional
    lev_value = equity * leverage                   # max with leverage
    return min(raw_value, lev_value) / price


def run_backtest(df: pd.DataFrame) -> dict:
    trades: list[dict] = []
    pos_side: int = 0  # 1=long, -1=short, 0=none
    entry_price: float = 0.0
    entry_equity: float = 1.0
    contracts: float = 0.0
    entry_regime: str = ""
    trail_stop: float = 0.0
    hard_stop: float = 0.0

    equity = [1.0]
    peak = 1.0
    max_dd = 0.0
    consec_losses = 0
    cooldown_until = -1

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        in_cooldown = i < cooldown_until

        # ── 强平检查 ──
        if pos_side != 0:
            margin = (contracts * price) / MAX_LEVERAGE
            if equity[-1] <= 0 or (margin > 0 and equity[-1] < margin * (1 - LIQ_THRESHOLD)):
                # Liquidation
                exit_px = exit_value(price)
                invested = entry_price * contracts
                if pos_side == 1:  # long
                    pnl = (exit_px - entry_price) * contracts
                else:  # short
                    pnl = (entry_price - exit_px) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = "liquidated"
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                new_eq = entry_equity + pnl
                equity[-1] = max(new_eq, 0.0001)
                peak = max(peak, equity[-1])
                max_dd = max(max_dd, (peak - equity[-1]) / peak)
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                pos_side = 0
                continue

        # ── 止损/止盈 ──
        if pos_side != 0:
            stop_hit = False
            reason = ""
            if pos_side == 1:  # long
                if price < trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row["close_sig"]) or bool(row["close_trend"]):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price < hard_stop:
                    stop_hit = True; reason = "hard_stop"
            else:  # short
                if price > trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row["cover_sig"]) or bool(row["cover_trend"]):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price > hard_stop:
                    stop_hit = True; reason = "hard_stop"

            if stop_hit:
                if pos_side == 1:
                    pnl = (exit_value(price) - entry_price) * contracts
                else:
                    pnl = (entry_price - entry_cost(price)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = reason
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                new_eq = entry_equity + pnl
                equity.append(max(new_eq, 0.0001))
                peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                pos_side = 0
                continue

        # ── 入场 ──
        if pos_side == 0 and not in_cooldown:
            enter_long = bool(row["long_sig"])
            enter_short = bool(row["short_sig"])
            if enter_long or enter_short:
                contracts = calc_contracts(equity[-1], price, atr_val, MAX_LEVERAGE)
                if enter_long:
                    pos_side = 1
                    ep = entry_cost(price)
                    entry_price = ep
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row["is_trend"]) else "mr"
                    trail_stop = price - atr_val * ATR_TRAIL_MULT
                    hard_stop = price - atr_val * MR_ATR_STOP_MULT
                else:
                    pos_side = -1
                    ep = exit_value(price)  # short entry: receive this
                    entry_price = ep
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row["is_trend"]) else "mr"
                    trail_stop = price + atr_val * ATR_TRAIL_MULT
                    hard_stop = price + atr_val * MR_ATR_STOP_MULT
                trades.append({
                    "entry_time": df.index[i], "entry_price": ep,
                    "contracts": contracts, "side": "LONG" if pos_side == 1 else "SHORT",
                    "regime": entry_regime, "exit_reason": None,
                    "exit_price": None, "return": None,
                })
                equity.append(equity[-1])
                continue

        # ── 跟踪止损 ──
        if pos_side == 1:
            trail_stop = max(trail_stop, price - atr_val * ATR_TRAIL_MULT)
        elif pos_side == -1:
            trail_stop = min(trail_stop, price + atr_val * ATR_TRAIL_MULT)

        # ── MTM + Funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i - 1]["close"])
            if pos_side == 1:
                pnl = contracts * (price - prev_price)
            else:
                pnl = contracts * (prev_price - price)
            funding_cost = (contracts * price) * FUNDING_RATE
            new_eq = equity[-1] + pnl - funding_cost
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
        else:
            equity.append(equity[-1])

    # 最终平仓
    if pos_side != 0:
        last_px = float(df.iloc[-1]["close"])
        if pos_side == 1:
            pnl = (exit_value(last_px) - entry_price) * contracts
        else:
            pnl = (entry_price - entry_cost(last_px)) * contracts
        ret = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = last_px
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    # ── 熔断逻辑（延迟检查，避免在循环中) ──
    # Moved to post-hoc: count max consecutive in _summarize

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    benchmark = df["close"] / df["close"].iloc[0]
    return _summarize(equity_series, benchmark, trades, df)


def _summarize(equity: pd.Series, benchmark: pd.Series, trades: list[dict], df: pd.DataFrame) -> dict:
    completed = [t for t in trades if t["return"] is not None]
    n = len(completed)
    if n == 0:
        return {"error": "no trades"}

    rets = [t["return"] for t in completed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    total_ret = float(equity.iloc[-1] - 1)
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    ann_ret = float((1+total_ret)**(1/n_years)-1) if n_years > 0 and total_ret > -1 else 0

    peak = equity.expanding().max()
    dd_series = (peak - equity) / peak
    max_dd = float(dd_series.max())

    daily_rets = equity.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25 * 6))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    bench_ret = float(benchmark.iloc[-1] - 1)
    bench_ann = float((1+bench_ret)**(1/n_years)-1) if n_years > 0 else 0

    long_trades = [t for t in completed if t.get("side") == "LONG"]
    short_trades = [t for t in completed if t.get("side") == "SHORT"]
    trend_trades = [t for t in completed if t.get("regime") == "trend"]
    mr_trades = [t for t in completed if t.get("regime") == "mr"]
    stops = [t for t in completed if "stop" in str(t.get("exit_reason", ""))]
    liqs = [t for t in completed if "liquid" in str(t.get("exit_reason", ""))]

    holding_hours = []
    for t in completed:
        if "entry_time" in t and "exit_time" in t:
            try:
                h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
                holding_hours.append(h)
            except: pass

    return {
        "total_return": round(total_ret * 100, 2),
        "annual_return": round(ann_ret * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "ann_volatility": round(ann_vol * 100, 2),
        "num_trades": n,
        "long_trades": len(long_trades), "short_trades": len(short_trades),
        "trend_trades": len(trend_trades), "mr_trades": len(mr_trades),
        "win_rate": round(len(wins)/n*100, 1) if n else 0,
        "avg_return": round(np.mean(rets)*100, 2),
        "avg_win": round(np.mean(wins)*100, 2) if wins else 0,
        "avg_loss": round(np.mean(losses)*100, 2) if losses else 0,
        "profit_factor": round(abs(sum(wins)/sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "stop_outs": len(stops), "liquidations": len(liqs),
        "benchmark_return": round(bench_ret*100, 2),
        "benchmark_annual": round(bench_ann*100, 2),
        "excess_return": round((ann_ret-bench_ann)*100, 2),
        "max_holding_hours": round(max(holding_hours), 1) if holding_hours else 0,
        "avg_holding_hours": round(np.mean(holding_hours), 1) if holding_hours else 0,
        "equity_curve": equity, "trades": completed,
    }


def print_report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR: {r['error']}"); return
    print(f"\n{'='*60}")
    print(f"ADX Adaptive + Perps {MAX_LEVERAGE:.0f}x Lev — 4h 2023-2026")
    print(f"Risk={RISK_PER_TRADE*100:.0f}%/trade | Funding={FUNDING_RATE*100:.4f}%/bar")
    print(f"{'='*60}")
    print(f"  Total Return:         {r['total_return']:>+8.2f}%")
    print(f"  Annual Return:        {r['annual_return']:>+8.2f}%")
    print(f"  Max Drawdown:         {r['max_drawdown']:>8.2f}%")
    print(f"  Sharpe Ratio:         {r['sharpe_ratio']:>8.3f}")
    print(f"  Calmar Ratio:         {r['calmar_ratio']:>8.3f}")
    print(f"  Annual Volatility:    {r['ann_volatility']:>8.2f}%")
    print()
    print(f"  Trades: {r['num_trades']} (L:{r['long_trades']} S:{r['short_trades']} | Trend:{r['trend_trades']} MR:{r['mr_trades']})")
    print(f"  Win Rate: {r['win_rate']}% | Avg Win: {r['avg_win']:+.2f}% | Avg Loss: {r['avg_loss']:+.2f}%")
    print(f"  Profit Factor: {r['profit_factor']} | Stops: {r['stop_outs']} | Liqs: {r['liquidations']}")
    print(f"  Max Holding: {r['max_holding_hours']:.0f}h | Avg: {r['avg_holding_hours']:.0f}h")
    print()
    print(f"  Benchmark (B&H ETH):  {r['benchmark_return']:>+8.2f}%")
    print(f"  Excess over B&H:      {r['excess_return']:>+8.2f}%")
    print(f"{'='*60}\n")


def main() -> int:
    logger.info("Loading data...")
    df = load_data()
    df = compute_signals(df)
    results = run_backtest(df)
    print_report(results)
    return 0

if __name__ == "__main__":
    sys.exit(main())

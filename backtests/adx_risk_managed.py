"""ADX 自适应 + 风控：波动率仓位 + 熔断 + 单笔上限。

Risk controls:
  - Vol-adaptive sizing: position = risk_pct / (ATR * atr_mult)
  - Max position cap: 20% of equity
  - Circuit breaker: 3 连亏 → 停 48 bars (8 days 4h)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"

FEE = 0.001
SLIPPAGE = 0.0005

ADX_PERIOD = 14
ADX_TREND = 25
ADX_RANGE = 20
DC_PERIOD = 20
ATR_TRAIL_MULT = 2.5
ATR_PERIOD = 14

RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
MR_ATR_STOP_MULT = 3.5

# 风控参数
RISK_PER_TRADE = 0.02      # 每笔风险 2%
MAX_POSITION_PCT = 0.50    # 单笔仓位上限 50%
CB_MAX_LOSSES = 5          # 连续亏损熔断阈值
CB_COOLDOWN_BARS = 24      # 熔断冷却期 (4 days)


def entry_cost(price: float) -> float:
    return price * (1 + SLIPPAGE) * (1 + FEE)

def exit_value(price: float) -> float:
    return price * (1 - SLIPPAGE) * (1 - FEE)


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    return df


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]
    high, low = df["high"], df["low"]

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ADX
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_adx = tr.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    up = high - high.shift()
    down = low.shift() - low
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_di = 100 * (plus_dm.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean() / atr_adx.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean() / atr_adx.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / ADX_PERIOD, min_periods=ADX_PERIOD).mean()

    # ATR
    df["atr"] = tr.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD).mean()

    # Donchian
    df["dc_high"] = high.rolling(DC_PERIOD).max()
    df["dc_low"] = low.rolling(DC_PERIOD).min()

    df["trend_entry"] = close > df["dc_high"].shift(1)
    df["trend_exit"] = close < df["dc_low"]
    df["mr_entry"] = df["rsi"] < RSI_OVERSOLD
    df["mr_exit"] = df["rsi"] > RSI_OVERBOUGHT
    df["regime_trend"] = df["adx"] > ADX_TREND
    df["regime_range"] = df["adx"] < ADX_RANGE

    raw = pd.Series(0.0, index=df.index)
    raw[df["regime_trend"] & df["trend_entry"]] = 1.0
    raw[df["regime_trend"] & df["trend_exit"]] = -1.0
    raw[df["regime_range"] & df["mr_entry"]] = 1.0
    raw[df["regime_range"] & df["mr_exit"]] = -1.0

    df["signal"] = raw.replace(0.0, np.nan).ffill().fillna(0.0)
    return df


def calc_position_size(equity: float, price: float, atr_val: float) -> float:
    """波动率自适应仓位：风险固定，波动大→仓位小。"""
    if atr_val <= 0:
        atr_val = price * 0.02
    risk_amount = equity * RISK_PER_TRADE
    raw_size = risk_amount / (atr_val * ATR_TRAIL_MULT)
    max_size = (equity * MAX_POSITION_PCT) / price
    return min(raw_size, max_size)


def run_backtest(df: pd.DataFrame) -> dict:
    trades: list[dict] = []
    in_position = False
    entry_price: float = 0.0
    entry_equity: float = 1.0
    position_size: float = 0.0
    entry_regime: str = ""
    trail_stop: float = 0.0
    hard_stop: float = 0.0

    equity = [1.0]
    peak = 1.0
    max_dd = 0.0
    consec_losses = 0
    cooldown_until = -1  # bar index when cooldown ends

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        sig = float(row["signal"])
        is_trend = bool(row["regime_trend"])

        # ── 熔断冷却 ──
        in_cooldown = i < cooldown_until
        if consec_losses >= CB_MAX_LOSSES and not in_cooldown and not in_position:
            cooldown_until = i + CB_COOLDOWN_BARS
            in_cooldown = True
            logger.info(f"{df.index[i]} Circuit breaker: {consec_losses} consec losses, pause {CB_COOLDOWN_BARS} bars")

        # ── 止损检查 ──
        if in_position:
            stop_hit = False
            exit_reason_str = ""
            if entry_regime == "trend" and price < trail_stop:
                stop_hit = True
                exit_reason_str = "trail_stop"
            elif entry_regime == "mr" and price < hard_stop:
                stop_hit = True
                exit_reason_str = "hard_stop"

            if stop_hit:
                exit_proceeds = exit_value(price) * position_size
                invested = entry_price * position_size
                cash = entry_equity - invested
                new_eq = cash + exit_proceeds
                ret = new_eq / entry_equity - 1
                trades[-1]["exit_reason"] = exit_reason_str
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                equity.append(new_eq)
                peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak)
                if ret <= 0: consec_losses += 1
                else: consec_losses = 0
                in_position = False
                continue

        # ── 信号出场 ──
        if in_position and sig == -1.0 and not in_cooldown:
            exit_proceeds = exit_value(price) * position_size
            invested = entry_price * position_size
            cash = entry_equity - invested
            new_eq = cash + exit_proceeds
            ret = new_eq / entry_equity - 1
            trades[-1]["exit_reason"] = "signal"
            trades[-1]["exit_price"] = price
            trades[-1]["return"] = ret
            trades[-1]["exit_time"] = df.index[i]
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak)
            if ret <= 0: consec_losses += 1
            else: consec_losses = 0
            in_position = False
            continue

        # ── 入场 ──
        if not in_position and sig == 1.0 and not in_cooldown:
            ec = entry_cost(price)
            entry_price = ec
            entry_equity = equity[-1]
            position_size = calc_position_size(entry_equity, price, atr_val)
            in_position = True
            if is_trend:
                entry_regime = "trend"
                trail_stop = price - atr_val * ATR_TRAIL_MULT
            elif bool(row["regime_range"]):
                entry_regime = "mr"
                hard_stop = price - atr_val * MR_ATR_STOP_MULT
            else:
                entry_regime = "unknown"
                hard_stop = price - atr_val * MR_ATR_STOP_MULT
            trades.append({
                "entry_time": df.index[i],
                "entry_price": ec,
                "position_size": position_size,
                "regime": entry_regime,
                "exit_reason": None,
                "exit_price": None,
                "return": None,
            })
            equity.append(equity[-1])
            continue

        # ── 跟踪止损更新 ──
        if in_position and entry_regime == "trend":
            trail_stop = max(trail_stop, price - atr_val * ATR_TRAIL_MULT)

        # ── MTM：权益 = 现金 + 持仓市值 ──
        if in_position:
            prev_price = float(df.iloc[i - 1]["close"])
            pnl = position_size * (price - prev_price)
            new_eq = equity[-1] + pnl
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak)
        else:
            equity.append(equity[-1])

    if in_position:
        exit_proceeds = exit_value(float(df.iloc[-1]["close"])) * position_size
        invested = entry_price * position_size
        cash = entry_equity - invested
        new_eq = cash + exit_proceeds
        ret = new_eq / entry_equity - 1
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = float(df.iloc[-1]["close"])
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = new_eq

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    benchmark = df["close"] / df["close"].iloc[0]
    return _summarize(equity_series, benchmark, trades, df)


def _summarize(equity: pd.Series, benchmark: pd.Series, trades: list[dict], df: pd.DataFrame) -> dict:
    completed = [t for t in trades if t["return"] is not None]
    n_trades = len(completed)
    if n_trades == 0:
        return {"error": "no trades"}

    returns = [t["return"] for t in completed]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    total_ret = float(equity.iloc[-1] - 1)
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    ann_ret = float((1 + total_ret) ** (1 / n_years) - 1) if n_years > 0 and total_ret > -1 else 0

    peak = equity.expanding().max()
    dd_series = (peak - equity) / peak
    max_dd = float(dd_series.max())

    daily_rets = equity.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25 * 6))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    bench_ret = float(benchmark.iloc[-1] - 1)
    bench_ann = float((1 + bench_ret) ** (1 / n_years) - 1) if n_years > 0 else 0

    holding_hours = []
    for t in completed:
        if "entry_time" in t and "exit_time" in t:
            try:
                h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
                holding_hours.append(h)
            except Exception:
                pass

    trend_trades = [t for t in completed if t.get("regime") == "trend"]
    mr_trades = [t for t in completed if t.get("regime") == "mr"]
    stops = [t for t in completed if "stop" in str(t.get("exit_reason", ""))]

    # 最大连续亏损
    max_cl = 0; cl = 0
    for r in returns:
        if r <= 0: cl += 1; max_cl = max(max_cl, cl)
        else: cl = 0
    max_cl = max(max_cl, cl)

    return {
        "total_return": round(total_ret * 100, 2),
        "annual_return": round(ann_ret * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "ann_volatility": round(ann_vol * 100, 2),
        "num_trades": n_trades,
        "trend_trades": len(trend_trades),
        "mr_trades": len(mr_trades),
        "win_rate": round(len(wins) / n_trades * 100, 1) if n_trades else 0,
        "avg_return": round(np.mean(returns) * 100, 2) if returns else 0,
        "avg_win": round(np.mean(wins) * 100, 2) if wins else 0,
        "avg_loss": round(np.mean(losses) * 100, 2) if losses else 0,
        "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "max_consec_losses": max_cl,
        "benchmark_return": round(bench_ret * 100, 2),
        "benchmark_annual": round(bench_ann * 100, 2),
        "excess_return": round((ann_ret - bench_ann) * 100, 2),
        "max_holding_hours": round(max(holding_hours), 1) if holding_hours else 0,
        "avg_holding_hours": round(np.mean(holding_hours), 1) if holding_hours else 0,
        "max_holding_bars": int(max(holding_hours) / 4) if holding_hours else 0,
        "stop_outs": len(stops),
        "equity_curve": equity,
        "trades": completed,
    }


def print_report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR: {r['error']}")
        return

    print(f"\n{'='*60}")
    print("ADX Adaptive + Risk Management — 4h 2023-2026")
    print(f"Risk={RISK_PER_TRADE*100:.0f}%/trade MaxPos={MAX_POSITION_PCT*100:.0f}% Circuit={CB_MAX_LOSSES}L→{CB_COOLDOWN_BARS}bars")
    print(f"{'='*60}")
    print(f"  Total Return:         {r['total_return']:>+8.2f}%")
    print(f"  Annual Return:        {r['annual_return']:>+8.2f}%")
    print(f"  Max Drawdown:         {r['max_drawdown']:>8.2f}%")
    print(f"  Sharpe Ratio:         {r['sharpe_ratio']:>8.3f}")
    print(f"  Calmar Ratio:         {r['calmar_ratio']:>8.3f}")
    print(f"  Annual Volatility:    {r['ann_volatility']:>8.2f}%")
    print()
    print(f"  Number of Trades:     {r['num_trades']:>8} (Trend:{r['trend_trades']} MR:{r['mr_trades']})")
    print(f"  Stop-outs:            {r['stop_outs']:>8}")
    print(f"  Win Rate:             {r['win_rate']:>8.1f}%")
    print(f"  Avg Return/Trade:     {r['avg_return']:>+8.2f}%")
    print(f"  Avg Win:              {r['avg_win']:>+8.2f}%")
    print(f"  Avg Loss:             {r['avg_loss']:>+8.2f}%")
    print(f"  Profit Factor:        {r['profit_factor']:>8.2f}")
    print(f"  Max Consec Losses:    {r['max_consec_losses']:>8}")
    print(f"  Max Holding:           {r['max_holding_hours']:>8.1f}h")
    print(f"  Avg Holding:           {r['avg_holding_hours']:>8.1f}h")
    print()
    print(f"  Benchmark (B&H ETH):  {r['benchmark_return']:>+8.2f}%")
    print(f"  Excess over B&H:      {r['excess_return']:>+8.2f}%")
    print(f"{'='*60}\n")


def main() -> int:
    logger.info("Loading Binance 4h data...")
    df = load_data()
    logger.info(f"Data: {len(df):,} rows")
    df = compute_signals(df)
    results = run_backtest(df)
    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

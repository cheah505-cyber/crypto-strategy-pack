"""Forward test $10,000 on any symbol with real per-bar funding rates."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
import backtests.adx_adaptive_perp_eth_4h as strat_mod

INITIAL_CAPITAL = 10_000
START_DATE = "2025-06-01"
END_DATE = "2026-05-25"

# ── 配置（改这里换币种）──────────────────────────────────────────────
SYMBOL = "BTC"              # ETH / BTC / SOL / BNB / ADA
DATA_FILE = f"data/{SYMBOL.lower()}_usdt_4h.csv"
FUNDING_FILE = f"data/eth_usdt_funding_rate.csv"  # BTC/ETH funding 高相关，暂时代理
SLIPPAGE = getattr(C, f"SLIPPAGE_{SYMBOL}", C.SLIPPAGE_ETH)
FUNDING_RATE = getattr(C, f"FUNDING_RATE_4H_{SYMBOL}", C.FUNDING_RATE_4H_ETH)

# ── 参数 ──
strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = SLIPPAGE
strat_mod.FUNDING_RATE = FUNDING_RATE
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

# 逐币参数覆盖（来自跨币分析结论）
if SYMBOL == "BTC":
    strat_mod.ADX_TREND = 40
    strat_mod.ADX_RANGE = 25
    strat_mod.ATR_TRAIL_MULT = 3.0
    strat_mod.MR_ATR_STOP_MULT = 4.0
else:
    strat_mod.ADX_TREND = 30
    strat_mod.ADX_RANGE = 15
    strat_mod.ATR_TRAIL_MULT = 2.5
    strat_mod.MR_ATR_STOP_MULT = 3.5


def load_funding_rates(path: Path) -> pd.Series:
    if not path.exists():
        print(f"  [no funding data, using constant {FUNDING_RATE*100:.4f}%/4h]")
        return pd.Series(dtype=float)
    df_fr = pd.read_csv(path, parse_dates=["timestamp"])
    df_fr = df_fr.set_index("timestamp").sort_index()
    if df_fr.index.tz is not None:
        df_fr.index = df_fr.index.tz_convert(None)
    rates_4h = df_fr["fundingRate"].resample("4h", label="right").ffill() / 2
    print(f"  Funding rates: {len(rates_4h)} records loaded")
    return rates_4h


def run_forward(df: pd.DataFrame, funding_rates: pd.Series) -> tuple[pd.Series, list[dict]]:
    """run_backtest 副本，支持真实资金费率 + $初始资金。"""
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # 必须重算信号（import 时已算过一次，保证独立）
    df = strat_mod.compute_signals(df)

    trades: list[dict] = []
    pos_side: int = 0
    entry_price: float = 0.0
    entry_equity: float = INITIAL_CAPITAL
    contracts: float = 0.0
    entry_regime: str = ""
    trail_stop: float = 0.0
    hard_stop: float = 0.0

    equity: list[float] = [INITIAL_CAPITAL]
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    consec_losses = 0
    cooldown_until = -1

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        in_cooldown = i < cooldown_until

        # 真实资金费率
        bar_time = df.index[i]
        if bar_time in funding_rates.index:
            fr = float(funding_rates.loc[bar_time])
        else:
            fr = strat_mod.FUNDING_RATE

        # ── 强平 ──
        if pos_side != 0:
            margin = (contracts * price) / strat_mod.MAX_LEVERAGE
            liq_thresh = 0.90
            if equity[-1] <= 0 or (margin > 0 and equity[-1] < margin * (1 - liq_thresh)):
                pnl = (strat_mod.exit_value(price) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(price)) * contracts
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
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 止损/平仓 ──
        if pos_side != 0:
            stop_hit = False
            reason = ""
            if pos_side == 1:
                if price < trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row.get("close_sig", False)) or bool(row.get("close_trend", False)):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price < hard_stop:
                    stop_hit = True; reason = "hard_stop"
            else:
                if price > trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row.get("cover_sig", False)) or bool(row.get("cover_trend", False)):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price > hard_stop:
                    stop_hit = True; reason = "hard_stop"

            if stop_hit:
                pnl = (strat_mod.exit_value(price) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(price)) * contracts
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
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 入场 ──
        if pos_side == 0 and not in_cooldown:
            enter_long = bool(row.get("long_sig", False))
            enter_short = bool(row.get("short_sig", False))
            if enter_long or enter_short:
                contracts = strat_mod.calc_contracts(equity[-1], price, atr_val, strat_mod.MAX_LEVERAGE)
                if enter_long:
                    pos_side = 1
                    entry_price = strat_mod.entry_cost(price)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price - atr_val * strat_mod.ATR_TRAIL_MULT
                    hard_stop = price - atr_val * strat_mod.MR_ATR_STOP_MULT
                else:
                    pos_side = -1
                    entry_price = strat_mod.exit_value(price)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price + atr_val * strat_mod.ATR_TRAIL_MULT
                    hard_stop = price + atr_val * strat_mod.MR_ATR_STOP_MULT
                trades.append({
                    "entry_time": df.index[i], "entry_price": entry_price,
                    "contracts": contracts, "side": "LONG" if pos_side == 1 else "SHORT",
                    "regime": entry_regime, "exit_reason": None,
                    "exit_price": None, "return": None,
                })
                equity.append(equity[-1])
                continue

        # ── 跟踪止损 ──
        if pos_side == 1:
            trail_stop = max(trail_stop, price - atr_val * strat_mod.ATR_TRAIL_MULT)
        elif pos_side == -1:
            trail_stop = min(trail_stop, price + atr_val * strat_mod.ATR_TRAIL_MULT)

        # ── MTM + funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i - 1]["close"])
            if pos_side == 1:
                pnl = contracts * (price - prev_price)
            else:
                pnl = contracts * (prev_price - price)
            funding_cost = (contracts * price) * fr
            new_eq = equity[-1] + pnl - funding_cost
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
        else:
            equity.append(equity[-1])

    # 最终平仓
    if pos_side != 0:
        last_px = float(df.iloc[-1]["close"])
        pnl = (strat_mod.exit_value(last_px) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(last_px)) * contracts
        ret = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = last_px
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    return pd.Series(equity[:len(df)], index=df.index), trades


def main():
    data_path = ROOT / DATA_FILE
    fund_path = ROOT / FUNDING_FILE

    print(f"Loading {SYMBOL} data: {data_path.name}")
    df = strat_mod.load_data(data_path)
    df = df[(df.index >= START_DATE) & (df.index < END_DATE)]
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    # 首次信号计算（给 _preflight 用）
    df = strat_mod.compute_signals(df)
    print(f"  Data: {df.index[0]} → {df.index[-1]} ({len(df)} bars)")
    print(f"  Params: ADX>{strat_mod.ADX_TREND}/<{strat_mod.ADX_RANGE}, ATR {strat_mod.ATR_TRAIL_MULT}x")

    # 资金费率
    funding_rates = load_funding_rates(fund_path)

    # 跑
    equity_curve, trades = run_forward(df, funding_rates)
    final_eq = equity_curve.iloc[-1]
    total_ret_pct = (final_eq / INITIAL_CAPITAL - 1) * 100

    # 计算指标
    n = len(trades)
    rets = [t["return"] for t in trades if t["return"] is not None]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n_years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
    ann_ret = ((1 + total_ret_pct / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    peak = equity_curve.expanding().max()
    dd_series = (peak - equity_curve) / peak
    max_dd = float(dd_series.max()) * 100
    daily_rets = equity_curve.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0
    benchmark = df["close"] / df["close"].iloc[0]
    bench_ret = (benchmark.iloc[-1] - 1) * 100
    bench_ann = ((1 + bench_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    long_trades = [t for t in trades if t.get("side") == "LONG"]
    short_trades = [t for t in trades if t.get("side") == "SHORT"]
    liqs = sum(1 for t in trades if "liquid" in str(t.get("exit_reason", "")))

    # 最长持仓
    holding_by_side = {"LONG": [], "SHORT": []}
    for t in trades:
        if t["entry_time"] and t["exit_time"]:
            h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
            holding_by_side[t["side"]].append(h)

    print(f"\n{'='*62}")
    print(f"  Forward Test: ${INITIAL_CAPITAL:,} {SYMBOL}/USDT 4h · 10x · Binance")
    print(f"  Period: {START_DATE} → {END_DATE} ({n_years:.1f} yrs)")
    print(f"{'='*62}")
    print(f"  起始资金:            ${INITIAL_CAPITAL:>8,.2f}")
    print(f"  期末资金:            ${final_eq:>8,.2f}")
    print(f"  总盈亏:              ${final_eq - INITIAL_CAPITAL:>+8,.2f}")
    print(f"  总收益率:            {total_ret_pct:>+8.2f}%")
    print(f"  年化收益:            {ann_ret:>+8.2f}%")
    print(f"  夏普比率:            {sharpe:>8.3f}")
    print(f"  最大回撤:            {max_dd:>7.2f}% (${max_dd/100*final_eq:>7,.0f})")
    print(f"  卡玛比率:            {calmar:>8.3f}")
    print(f"  交易次数:            {n:>8}")
    print(f"  做多/做空:           {len(long_trades):>3}/{len(short_trades):>3}")
    print(f"  胜率:                {len(wins)/n*100 if n else 0:>7.1f}%")
    print(f"  盈亏比:              {abs(sum(wins)/sum(losses)) if wins and sum(losses) != 0 else 0:>8.2f}")
    print(f"  强平:                {liqs:>8}")
    print(f"  对比 B&H {SYMBOL}:       {bench_ret:>+8.2f}%")
    print(f"  超额收益(ann):       {ann_ret - bench_ann:>+8.2f}%")
    print()

    for side, hours in holding_by_side.items():
        if hours:
            print(f"  {side} 持仓:")
            print(f"    最长: {max(hours):.0f}h ({max(hours)/24:.1f}d)")
            print(f"    最短: {min(hours):.0f}h")
            print(f"    平均: {np.mean(hours):.0f}h ({np.mean(hours)/24:.1f}d)")
    print()

    # 月盈亏
    trade_df = pd.DataFrame([t for t in trades if t["return"] is not None])
    if len(trade_df):
        eq = INITIAL_CAPITAL
        monthly: dict[str, float] = {}
        trade_df["entry_time"] = pd.to_datetime(trade_df["entry_time"])
        trade_df["month"] = trade_df["entry_time"].dt.strftime("%Y-%m")
        for m, grp in trade_df.groupby("month"):
            m_eq = eq
            for _, t in grp.iterrows():
                eq *= (1 + t["return"])
            monthly[m] = (eq / m_eq - 1) * 100

        print(f"  每月收益率:")
        for m, ret_pct in sorted(monthly.items()):
            bar_len = max(1, min(int(abs(ret_pct) * 2), 60))
            bar = "█" * bar_len
            print(f"    {m}: {ret_pct:>+6.2f}% {bar}")
    print()


if __name__ == "__main__":
    main()

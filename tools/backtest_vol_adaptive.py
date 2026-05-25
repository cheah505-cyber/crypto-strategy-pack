"""波动率自适应策略：根据 30 天滚动波动率切换参数。

< 55% 低波动: ATR 4.0x, 正常仓位
55-80% 中波动: ATR 2.5x, 正常仓位 (4h 基线)
> 80% 高波动: ATR 2.0x, 仓位减半
"""
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
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals, _preflight

INITIAL_CAPITAL = 10_000
DATA_PATH = ROOT / "data" / "eth_usdt_4h.csv"

# 基线参数
strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def run_vol_adaptive(df: pd.DataFrame) -> dict:
    """run_backtest 副本 + 波动率自适应。"""
    _preflight(df)

    # 滚动波动率
    ret = df["close"].pct_change()
    df["vol_30d"] = ret.rolling(180).std() * np.sqrt(365.25 * 6) * 100

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
    feez = strat_mod.FEE
    slipp = strat_mod.SLIPPAGE
    fr = strat_mod.FUNDING_RATE

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        in_cooldown = i < cooldown_until

        # 当前波动率 → 动态参数
        vol = row.get("vol_30d", np.nan)
        if pd.notna(vol):
            if vol < 55:
                atr_m = 4.0
                risk_pct = 0.04
            elif vol < 80:
                atr_m = 2.5
                risk_pct = 0.04
            else:
                atr_m = 2.0
                risk_pct = 0.02  # 高波动仓位减半
        else:
            atr_m = 2.5
            risk_pct = 0.04

        # ── 强平 ──
        if pos_side != 0:
            margin = (contracts * price) / strat_mod.MAX_LEVERAGE
            liq_thresh = 0.90
            if equity[-1] <= 0 or (margin > 0 and equity[-1] < margin * (1 - liq_thresh)):
                pnl = (price * (1 - slipp) * (1 - feez) - entry_price) * contracts if pos_side == 1 else (entry_price - price * (1 + slipp) * (1 + feez)) * contracts
                ret_pnl = pnl / entry_equity
                trades[-1]["exit_reason"] = "liquidated"
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret_pnl
                trades[-1]["exit_time"] = df.index[i]
                equity[-1] = max(entry_equity + pnl, 0.0001)
                peak = max(peak, equity[-1])
                max_dd = max(max_dd, (peak - equity[-1]) / peak)
                consec_losses = consec_losses + 1 if ret_pnl <= 0 else 0
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 止损/平仓 ──
        if pos_side != 0:
            stop_hit = False
            reason = ""
            if pos_side == 1:
                if price < trail_stop: stop_hit = True; reason = "trail_stop"
                elif bool(row.get("close_sig", False)) or bool(row.get("close_trend", False)): stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price < hard_stop: stop_hit = True; reason = "hard_stop"
            else:
                if price > trail_stop: stop_hit = True; reason = "trail_stop"
                elif bool(row.get("cover_sig", False)) or bool(row.get("cover_trend", False)): stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price > hard_stop: stop_hit = True; reason = "hard_stop"

            if stop_hit:
                pnl = (price * (1 - slipp) * (1 - feez) - entry_price) * contracts if pos_side == 1 else (entry_price - price * (1 + slipp) * (1 + feez)) * contracts
                ret_pnl = pnl / entry_equity
                trades[-1]["exit_reason"] = reason
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret_pnl
                trades[-1]["exit_time"] = df.index[i]
                new_eq = max(entry_equity + pnl, 0.0001)
                equity.append(new_eq)
                peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
                consec_losses = consec_losses + 1 if ret_pnl <= 0 else 0
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 入场 ──
        if pos_side == 0 and not in_cooldown:
            enter_long = bool(row.get("long_sig", False))
            enter_short = bool(row.get("short_sig", False))
            if enter_long or enter_short:
                # 动态风险
                if atr_val <= 0: atr_val = price * 0.02
                risk_amount = equity[-1] * risk_pct
                stop_dist = atr_val * atr_m
                raw_value = risk_amount / (stop_dist / price)
                lev_value = equity[-1] * strat_mod.MAX_LEVERAGE
                contracts = min(raw_value, lev_value) / price

                if enter_long:
                    pos_side = 1
                    entry_price = price * (1 + slipp) * (1 + feez)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price - atr_val * atr_m
                    hard_stop = price - atr_val * (atr_m + 1.0)
                else:
                    pos_side = -1
                    entry_price = price * (1 - slipp) * (1 - feez)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price + atr_val * atr_m
                    hard_stop = price + atr_val * (atr_m + 1.0)

                trades.append({
                    "entry_time": df.index[i], "entry_price": entry_price,
                    "contracts": contracts, "side": "LONG" if pos_side == 1 else "SHORT",
                    "regime": entry_regime, "exit_reason": None,
                    "exit_price": None, "return": None,
                    "vol_regime": "low" if vol < 55 else "med" if vol < 80 else "high",
                })
                equity.append(equity[-1])
                continue

        # ── 跟踪止损 ──
        if pos_side == 1:
            trail_stop = max(trail_stop, price - atr_val * atr_m)
        elif pos_side == -1:
            trail_stop = min(trail_stop, price + atr_val * atr_m)

        # ── MTM + funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i - 1]["close"])
            pnl = contracts * (price - prev_price) if pos_side == 1 else contracts * (prev_price - price)
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
        pnl = (last_px * (1 - slipp) * (1 - feez) - entry_price) * contracts if pos_side == 1 else (entry_price - last_px * (1 + slipp) * (1 + feez)) * contracts
        ret_pnl = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = last_px
        trades[-1]["return"] = ret_pnl
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    benchmark = df["close"] / df["close"].iloc[0]

    # 指标
    completed = [t for t in trades if t["return"] is not None]
    n = len(completed)
    rets = [t["return"] for t in completed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    total_ret = float(equity_series.iloc[-1] / INITIAL_CAPITAL - 1) * 100
    n_years = (equity_series.index[-1] - equity_series.index[0]).days / 365.25
    ann_ret = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else 0
    peak_s = equity_series.expanding().max()
    dd_s = (peak_s - equity_series) / peak_s
    max_dd = float(dd_s.max()) * 100
    daily_rets = equity_series.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0
    bench_ret = float(benchmark.iloc[-1] - 1) * 100
    long_t = [t for t in completed if t.get("side") == "LONG"]
    short_t = [t for t in completed if t.get("side") == "SHORT"]
    liqs = sum(1 for t in completed if "liquid" in str(t.get("exit_reason", "")))
    vol_regimes = pd.Series([t.get("vol_regime", "?") for t in completed])

    return {
        "total_return": round(total_ret, 2),
        "annual_return": round(ann_ret, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "num_trades": n,
        "long_trades": len(long_t), "short_trades": len(short_t),
        "win_rate": round(len(wins)/n*100, 1) if n else 0,
        "profit_factor": round(abs(sum(wins)/sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "liquidations": liqs,
        "benchmark_return": round(bench_ret, 2),
        "trades_low_vol": int((vol_regimes == "low").sum()),
        "trades_med_vol": int((vol_regimes == "med").sum()),
        "trades_high_vol": int((vol_regimes == "high").sum()),
    }


# ── 运行 ──
df = load_data(DATA_PATH)
if df.index.tz is not None: df.index = df.index.tz_localize(None)
df = compute_signals(df)

print("=" * 70)
print("  波动率自适应策略 — Full Cycle 2019-2026")
print("=" * 70)

r = run_vol_adaptive(df)
if "error" in r:
    print(f"  ERROR: {r['error']}")
else:
    final = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
    print(f"  Final:           ${final:>8,.0f}")
    print(f"  Total Return:    {r['total_return']:>+8.1f}%")
    print(f"  Annual Return:   {r['annual_return']:>+8.1f}%")
    print(f"  Sharpe Ratio:    {r['sharpe_ratio']:>8.3f}")
    print(f"  Max Drawdown:    {r['max_drawdown']:>7.1f}%")
    print(f"  Calmar Ratio:    {r['calmar_ratio']:>8.3f}")
    print(f"  Trades:          {r['num_trades']:>8} (L:{r['long_trades']} S:{r['short_trades']})")
    print(f"  Win Rate:        {r['win_rate']:>7.1f}%")
    print(f"  Profit Factor:   {r['profit_factor']:>8.2f}")
    print(f"  Liquidations:    {r['liquidations']:>8}")
    print(f"  Bench B&H:       {r['benchmark_return']:>+8.1f}%")
    print(f"  Trades by vol:   Low:{r['trades_low_vol']} Med:{r['trades_med_vol']} High:{r['trades_high_vol']}")
    print()

# 对比
print("=" * 70)
print("  对比 4h 基线")
print("=" * 70)
strat_mod.FEE = C.FEE_TAKER; strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30; strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 2.5; strat_mod.MR_ATR_STOP_MULT = 3.5
baseline = strat_mod.run_backtest(df)
final_b = INITIAL_CAPITAL * (1 + baseline["total_return"] / 100)
print(f"  Baseline Final:  ${final_b:>8,.0f}  Ret {baseline['total_return']:>+7.1f}%  "
      f"Sharpe {baseline['sharpe_ratio']:.3f}  DD {baseline['max_drawdown']:.1f}%")
print(f"  Adaptive Final:  ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
      f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%")
print()

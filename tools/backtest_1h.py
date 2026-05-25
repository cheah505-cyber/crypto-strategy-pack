"""ETH 1h 全周期回测 + Walk-Forward (ADX>30/<15, ATR 4.2x, Binance 真实费率)"""
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

DATA_PATH = ROOT / "data" / "eth_usdt_1h.csv"
FUNDING_PATH = ROOT / "data" / "eth_usdt_funding_rate.csv"

# ── 1h 参数 ──
strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH  # 0.001633%/1h bar
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 4.2
strat_mod.MR_ATR_STOP_MULT = 5.2
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

# ── 1. 全周期回测 ──────────────────────────────────────────────
print("=" * 70)
print("  ETH 1h Full-Cycle Backtest")
print("=" * 70)

df = strat_mod.load_data(DATA_PATH)
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)
df = strat_mod.compute_signals(df)
print(f"  Data: {df.index[0]} → {df.index[-1]} ({len(df)} bars)")

r = strat_mod.run_backtest(df)
if "error" in r:
    print(f"  ERROR: {r['error']}")
    sys.exit(1)

# 最长持仓
max_long_h, max_short_h = 0, 0
for t in r.get("trades", []):
    if t["entry_time"] and t["exit_time"]:
        h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
        if t["side"] == "LONG":
            max_long_h = max(max_long_h, h)
        else:
            max_short_h = max(max_short_h, h)

print(f"  {'='*60}")
print(f"  Total Return:         {r['total_return']:>+8.2f}%")
print(f"  Annual Return:        {r['annual_return']:>+8.2f}%")
print(f"  Max Drawdown:         {r['max_drawdown']:>8.2f}%")
print(f"  Sharpe Ratio:         {r['sharpe_ratio']:>8.3f}")
print(f"  Calmar Ratio:         {r['calmar_ratio']:>8.3f}")
print(f"  Trades: {r['num_trades']} (L:{r['long_trades']} S:{r['short_trades']} | T:{r['trend_trades']} MR:{r['mr_trades']})")
print(f"  Win Rate: {r['win_rate']}% | PF: {r['profit_factor']} | Liqs: {r['liquidations']}")
print(f"  Bench B&H: {r['benchmark_return']:+.2f}%")
print(f"  Excess ann: {r['excess_return']:+.2f}%")
print(f"  Max Long:  {max_long_h/24:.1f}d | Max Short: {max_short_h/24:.1f}d")
print()

# ── 2. Walk-Forward ──────────────────────────────────────────
print("=" * 70)
print("  Walk-Forward: 4m IS / 2m OOS (step 2m)")
print("=" * 70)

WF_WINDOW = 4    # months IS
WF_STEP = 2      # months OOS + step
WF_MIN_TRADES = 10
ATR_GRID_1H = [3.0, 3.5, 4.0, 4.2, 4.5, 5.0]

start_dates = pd.date_range(
    start=df.index.min() + pd.DateOffset(months=WF_WINDOW),
    end=df.index.max() - pd.DateOffset(months=WF_STEP),
    freq=pd.DateOffset(months=WF_STEP),
)

windows = []
cum_eq = 1.0

for i, wf_start in enumerate(start_dates):
    oos_start = wf_start
    oos_end = wf_start + pd.DateOffset(months=WF_STEP)
    is_start = wf_start - pd.DateOffset(months=WF_WINDOW)

    df_is = df[(df.index >= is_start) & (df.index < oos_start)].copy()
    df_oos = df[(df.index >= oos_start) & (df.index < oos_end)].copy()

    if len(df_is) < 500 or len(df_oos) < 200:
        continue

    best_atr = None
    best_sh = -999
    for atr_m in ATR_GRID_1H:
        # 在样本内搜索最优 ATR
        strat_mod.ATR_TRAIL_MULT = atr_m
        strat_mod.MR_ATR_STOP_MULT = atr_m + 1.0
        rr = strat_mod.run_backtest(df_is.copy())
        if rr and "error" not in rr and rr["num_trades"] >= WF_MIN_TRADES and rr["sharpe_ratio"] > best_sh:
            best_sh = rr["sharpe_ratio"]
            best_atr = atr_m

    if best_atr is None:
        continue

    # 样本外
    strat_mod.ATR_TRAIL_MULT = best_atr
    strat_mod.MR_ATR_STOP_MULT = best_atr + 1.0
    rr_oos = strat_mod.run_backtest(df_oos.copy())
    if rr_oos is None or "error" in rr_oos:
        continue

    cum_eq *= (1 + rr_oos["total_return"] / 100)
    windows.append({
        "oos_period": f"{oos_start.date()}→{oos_end.date()}",
        "best_atr": best_atr,
        "is_sh": best_sh,
        "oos_ret": rr_oos["total_return"],
        "oos_sh": rr_oos["sharpe_ratio"],
        "oos_dd": rr_oos["max_drawdown"],
        "oos_trades": rr_oos["num_trades"],
        "oos_pf": rr_oos["profit_factor"],
        "liqs": rr_oos["liquidations"],
    })

if not windows:
    print("  No valid windows")
else:
    print(f"  Windows: {len(windows)}")
    print(f"  {'OOS Period':<22} {'ATR':<5} {'OOS Ret':>8} {'OOS Sh':>7} {'DD':>7} {'PF':>6} {'Trades':>6} {'Liq':>4}")
    print("  " + "-" * 73)
    for w in windows:
        print(f"  {w['oos_period']:<22} {w['best_atr']:<5.1f}x {w['oos_ret']:>+7.1f}% {w['oos_sh']:>7.3f} {w['oos_dd']:>6.1f}% {w['oos_pf']:>5.2f} {w['oos_trades']:>6} {w['liqs']:>4}")

    total = len(windows)
    positive = sum(1 for w in windows if w["oos_ret"] > 0)
    cum_ret = (cum_eq - 1) * 100

    print(f"\n  Positive OOS: {positive}/{total} ({positive/total*100:.0f}%)")
    print(f"  Cumulative OOS: {cum_ret:+.2f}% (equity {cum_eq:.4f}x)")
    print(f"  Zero liqs: {'YES' if sum(w['liqs'] for w in windows) == 0 else 'NO'}")

    if positive / total >= 0.6 and cum_ret > 0:
        print(f"  === PASS ===")
    elif positive / total >= 0.5 and cum_ret > 0:
        print(f"  === WARN ===")
    else:
        print(f"  === FAIL ===")

print()

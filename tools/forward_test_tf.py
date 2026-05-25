"""Forward test $10,000 ETH on multiple timeframes with current baseline."""
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

# (label, data_file, funding_per_bar, atr_mult)
TIMEFRAMES = [
    ("1h",  "eth_usdt_1h.csv",  C.FUNDING_RATE_1H_ETH, 4.2),
    ("4h",  "eth_usdt_4h.csv",  C.FUNDING_RATE_4H_ETH, 2.5),
    ("1d",  "eth_usdt_1d.csv",  C.FUNDING_RATE_8H_ETH * 3, 3.6),  # 1d bar = 3 funding periods
]


def run_tf(label: str, data_file: str, fr_per_bar: float, atr_m: float) -> dict:
    strat_mod.FEE = C.FEE_TAKER
    strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
    strat_mod.FUNDING_RATE = fr_per_bar
    strat_mod.ADX_TREND = 30
    strat_mod.ADX_RANGE = 15
    strat_mod.ATR_TRAIL_MULT = atr_m
    strat_mod.MR_ATR_STOP_MULT = atr_m + 1.0
    strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

    df = strat_mod.load_data(ROOT / "data" / data_file)
    df = df[(df.index >= START_DATE) & (df.index < END_DATE)]
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = strat_mod.compute_signals(df)

    # 简化：直接用 run_backtest 缩放
    r = strat_mod.run_backtest(df)
    if "error" in r:
        return {"label": label, "error": r["error"]}

    final_eq = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
    peak = INITIAL_CAPITAL
    dd = r["max_drawdown"] / 100
    max_dd_dollars = dd * final_eq

    # 最长持仓
    max_long_h, max_short_h = 0, 0
    for t in r.get("trades", []):
        if t["entry_time"] and t["exit_time"]:
            h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
            if t["side"] == "LONG":
                max_long_h = max(max_long_h, h)
            else:
                max_short_h = max(max_short_h, h)

    return {
        "label": label,
        "final": round(final_eq, 2),
        "pnl": round(final_eq - INITIAL_CAPITAL, 2),
        "ret": r["total_return"],
        "ann": r["annual_return"],
        "sharpe": r["sharpe_ratio"],
        "dd": r["max_drawdown"],
        "dd_dollar": round(max_dd_dollars, 0),
        "trades": r["num_trades"],
        "long": r["long_trades"],
        "short": r["short_trades"],
        "win_rate": r["win_rate"],
        "pf": r["profit_factor"],
        "liqs": r["liquidations"],
        "bench": r["benchmark_return"],
        "max_long_h": max_long_h,
        "max_short_h": max_short_h,
    }


print(f"{'='*90}")
print(f"  ETH Forward Test: $10,000 · 10x · Binance 真实费率 · All Timeframes")
print(f"  Period: {START_DATE} → {END_DATE}")
print(f"{'='*90}")
print()

results = []
for label, data_file, fr, atr in TIMEFRAMES:
    r = run_tf(label, data_file, fr, atr)
    results.append(r)

# 表头
print(f"{'TF':<4} {'ADX':<8} {'ATR':<6} {'Final':>10} {'PNL':>10} {'Ret':>8} {'Sharpe':>8} {'DD':>7} {'Trades':>6} {'L/S':<8} {'Win%':>6} {'PF':>6} {'Liq':>4} {'MaxLng':>8} {'MaxSht':>8}")
print("-" * 113)

for r in results:
    if "error" in r:
        print(f"{r['label']:<4} ERROR: {r['error']}")
        continue
    ls = f"{r['long']}/{r['short']}"
    ml = f"{r['max_long_h']/24:.0f}d" if r['max_long_h'] else "-"
    ms = f"{r['max_short_h']/24:.0f}d" if r['max_short_h'] else "-"
    print(f"{r['label']:<4} 30/15    {r.get('atr', '2.5'):<6} "
          f"${r['final']:>8,.0f} ${r['pnl']:>+8,.0f} {r['ret']:>+7.1f}% "
          f"{r['sharpe']:>8.3f} {r['dd']:>6.1f}% {r['trades']:>6} "
          f"{ls:<8} {r['win_rate']:>5.1f}% {r['pf']:>5.2f} {r['liqs']:>4} "
          f"{ml:>8} {ms:>8}")

print()

# 图表对比
print(f"  $10K 对比:")
for r in results:
    if "error" in r:
        continue
    bar = "█" * max(1, int(abs(r["ret"]) / 2))
    print(f"  {r['label']:>4}: ${r['final']:>8,.0f}  {bar} {r['ret']:+.1f}%")

print()

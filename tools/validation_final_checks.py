"""最终盲区检查：funding极端 + 多时框 + ATR×ADX交互."""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from pathlib import Path
from backtests.adx_adaptive_perp_eth_4h import (
    load_data, compute_signals, run_backtest, DATA_PATH,
    FUNDING_RATE, ATR_TRAIL_MULT, ADX_TREND, ADX_RANGE
)
import backtests.adx_adaptive_perp_eth_4h as mod

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ═══════════════════════════════════════
# 1. FUNDING RATE EXTREME TEST
# ═══════════════════════════════════════
print("=" * 70)
print("1. FUNDING RATE STRESS TEST (ETH)")
print("=" * 70)
print(f"  Base: {FUNDING_RATE*100:.4f}%/bar | Scenarios: -5x to +5x")

df = load_data(DATA_PATH)

scenarios = [
    (0.0, "Zero funding"),
    (FUNDING_RATE * 3, "3x normal (bull)"),
    (FUNDING_RATE * 5, "5x normal (extreme bull)"),
    (-FUNDING_RATE * 3, "Negative (bear rebate)"),
    (-FUNDING_RATE * 5, "Highly negative (extreme bear)"),
]

original_fr = mod.FUNDING_RATE
for rate, label in scenarios:
    mod.FUNDING_RATE = rate
    df_s = compute_signals(df.copy())
    r = run_backtest(df_s)
    print(f"  {label:<28} FR={rate*100:.4f}%/bar → "
          f"Ret={r['total_return']:+.1f}% Sharpe={r['sharpe_ratio']:.3f} "
          f"DD={r['max_drawdown']:.1f}% PF={r['profit_factor']:.2f}")
mod.FUNDING_RATE = original_fr

# ═══════════════════════════════════════
# 2. MULTI-TIMEFRAME
# ═══════════════════════════════════════
print()
print("=" * 70)
print("2. MULTI-TIMEFRAME VALIDATION (ETH)")
print("=" * 70)

timeframes = {
    "1h": ("eth_usdt_1h.csv", 365.25 * 24),
    "4h": ("eth_usdt_4h.csv", 365.25 * 6),
    "1d": ("eth_usdt_1d.csv", 365.25),
}

# Fetch 1d data if missing
d1_path = PROJECT_ROOT / "data" / "eth_usdt_1d.csv"
if not d1_path.exists():
    import subprocess
    subprocess.run([
        "C:/Users/cheah/Python312/python.exe",
        str(PROJECT_ROOT / "tools" / "fetch_ohlcv.py"),
        "--symbol", "ETH/USDT", "--timeframe", "1d",
        "--since", "2023-01-01"
    ], capture_output=True)

for tf, (fname, bars_per_year) in timeframes.items():
    fpath = PROJECT_ROOT / "data" / fname
    if not fpath.exists():
        print(f"  {tf}: data file missing ({fpath})")
        continue
    df_tf = pd.read_csv(fpath, parse_dates=["timestamp"], index_col="timestamp")
    df_tf = compute_signals(df_tf)

    # Adapt IC window for timeframe
    orig_bpy = 365.25 * 6
    mod.ATR_PERIOD = 14  # same across all
    mod.ADX_PERIOD = 14

    r = run_backtest(df_tf)
    print(f"  {tf:<6} rows={len(df_tf):>6,}  "
          f"Ret={r['total_return']:+.1f}%  Sharpe={r['sharpe_ratio']:.3f}  "
          f"DD={r['max_drawdown']:.1f}%  PF={r['profit_factor']:.2f}  "
          f"Trades={r['num_trades']}")

# ═══════════════════════════════════════
# 3. ATR × ADX INTERACTION GRID (4h only)
# ═══════════════════════════════════════
print()
print("=" * 70)
print("3. ATR x ADX INTERACTION GRID (ETH 4h)")
print("=" * 70)

atr_grid = [1.5, 2.0, 2.5, 3.0, 3.5]
adx_grid = [(25, 15), (25, 20), (30, 15), (30, 20), (35, 20), (35, 25)]

df = load_data(DATA_PATH)

# Build grid
print(f"{'ADX\\ATR':<14}", end="")
for a in atr_grid:
    print(f"{'ATR=' + str(a):>13}", end="")
print(f"{'  Best':>10}")
print("-" * (14 + 13 * len(atr_grid) + 10))

grid_results = {}
for adx_hi, adx_lo in adx_grid:
    row_label = f"ADX>{adx_hi}/<{adx_lo}"
    print(f"{row_label:<14}", end="")
    best_sharpe = -999
    best_atr = None
    for atr_m in atr_grid:
        mod.ATR_TRAIL_MULT = atr_m
        mod.MR_ATR_STOP_MULT = atr_m + 1.0
        mod.ADX_TREND = adx_hi
        mod.ADX_RANGE = adx_lo
        df_s = compute_signals(df.copy())
        r = run_backtest(df_s)
        sharpe = r.get("sharpe_ratio", -999)
        print(f"{sharpe:>8.3f}  ", end="")
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_atr = atr_m
        grid_results[(adx_hi, adx_lo, atr_m)] = sharpe
    print(f"  best={best_sharpe:.3f}@{best_atr}x")

# Restore
mod.ATR_TRAIL_MULT = ATR_TRAIL_MULT
mod.MR_ATR_STOP_MULT = ATR_TRAIL_MULT + 1.0
mod.ADX_TREND = ADX_TREND
mod.ADX_RANGE = ADX_RANGE

# Summary
all_sharpes = list(grid_results.values())
current = grid_results.get((ADX_TREND, ADX_RANGE, ATR_TRAIL_MULT), 0)
print()
print(f"  Sharpe range: {min(all_sharpes):.3f} ~ {max(all_sharpes):.3f}")
print(f"  Current (ADX>{ADX_TREND}/<{ADX_RANGE} ATR={ATR_TRAIL_MULT}x): {current:.3f}")
print(f"  % combos with Sharpe > 0: {sum(1 for s in all_sharpes if s > 0)/len(all_sharpes)*100:.0f}%")
print(f"  % combos with Sharpe > 1.0: {sum(1 for s in all_sharpes if s > 1.0)/len(all_sharpes)*100:.0f}%")

# Stability: if we randomly pick a param, what's the expected Sharpe?
print(f"  Mean Sharpe across grid: {np.mean(all_sharpes):.3f}")
print(f"  Std Sharpe across grid:  {np.std(all_sharpes):.3f}")

# Check if current params are in top N%
rank = sum(1 for s in all_sharpes if s > current) / len(all_sharpes) * 100
print(f"  Current params better than {100-rank:.0f}% of grid")

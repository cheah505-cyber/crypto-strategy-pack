"""Walk-Forward: 2-regime (old) vs 3-regime (new) on identical windows.

IS: 8 months, OOS: 4 months, step: 2 months.
IS optimization: grid search ATR multipliers per regime.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))
import constants as C

# ── Run old 2-regime on a window ──
def _run_2regime(df, atr_trail):
    import importlib
    import backtests.adx_adaptive_perp_eth_4h as s
    importlib.reload(s)
    s.ATR_TRAIL_MULT = atr_trail
    # disable transition mode for old comparison
    orig_sigs = s.compute_signals.__code__
    df_s = s.compute_signals(df)
    # zero out transition signals to emulate old 2-regime
    df_s["long_sig"] = df_s["long_sig"] & ~df_s["is_transition"]
    df_s["short_sig"] = df_s["short_sig"] & ~df_s["is_transition"]
    r = s.run_backtest(df_s)
    return r

# ── Run new 3-regime on a window ──
def _run_3regime(df, trend_atr, trans_atr):
    import importlib
    import backtests.adx_adaptive_perp_eth_4h as s
    importlib.reload(s)
    s.ATR_TRAIL_MULT = trend_atr
    s.TRAN_ATR_TRAIL_MULT = trans_atr
    df_s = s.compute_signals(df)
    r = s.run_backtest(df_s)
    return r

# ── Load data ──
import backtests.adx_adaptive_perp_eth_4h as strat

df_full = strat.load_data()
print(f"Data: {df_full.index.min()} → {df_full.index.max()} ({len(df_full)} bars)")

IS_MONTHS = 8
OOS_MONTHS = 4
STEP_MONTHS = 2
MIN_TRADES = 5

ATR_GRID_OLD = [1.5, 2.0, 2.5, 3.0, 3.5]
ATR_TREND_GRID = [2.0, 2.5, 3.0]
ATR_TRANS_GRID = [1.0, 1.5, 2.0]

start_dates = pd.date_range(
    start=df_full.index.min() + pd.DateOffset(months=IS_MONTHS),
    end=df_full.index.max() - pd.DateOffset(months=OOS_MONTHS),
    freq=pd.DateOffset(months=STEP_MONTHS),
)

old_windows = []
new_windows = []

for wf_start in start_dates:
    oos_start = wf_start
    oos_end = wf_start + pd.DateOffset(months=OOS_MONTHS)
    is_start = wf_start - pd.DateOffset(months=IS_MONTHS)

    is_df = df_full[(df_full.index >= is_start) & (df_full.index < oos_start)].copy()
    oos_df = df_full[(df_full.index >= oos_start) & (df_full.index < oos_end)].copy()

    if len(is_df) < 200 or len(oos_df) < 100:
        continue

    # ── OLD: optimize ATR_TRAIL_MULT ──
    best_old = None
    best_old_sh = -999
    for atr in ATR_GRID_OLD:
        r = _run_2regime(is_df, atr)
        if ("error" not in r and r["num_trades"] >= MIN_TRADES
                and r["sharpe_ratio"] > best_old_sh):
            best_old_sh = r["sharpe_ratio"]
            best_old = atr

    if best_old is not None:
        r_old_oos = _run_2regime(oos_df, best_old)
        if "error" not in r_old_oos and r_old_oos["num_trades"] >= MIN_TRADES:
            old_windows.append({
                "period": f"{oos_start.date()}→{oos_end.date()}",
                "best_atr": best_old,
                "oos_ret": r_old_oos["total_return"],
                "oos_sh": r_old_oos["sharpe_ratio"],
                "oos_dd": r_old_oos["max_drawdown"],
                "oos_trades": r_old_oos["num_trades"],
                "oos_pf": r_old_oos["profit_factor"],
                "liqs": r_old_oos["liquidations"],
            })

    # ── NEW: optimize trend + trans ATR ──
    best_new = None
    best_new_sh = -999
    for t_atr in ATR_TREND_GRID:
        for x_atr in ATR_TRANS_GRID:
            r = _run_3regime(is_df, t_atr, x_atr)
            if ("error" not in r and r["num_trades"] >= MIN_TRADES
                    and r["sharpe_ratio"] > best_new_sh):
                best_new_sh = r["sharpe_ratio"]
                best_new = (t_atr, x_atr)

    if best_new is not None:
        t_a, x_a = best_new
        r_new_oos = _run_3regime(oos_df, t_a, x_a)
        if "error" not in r_new_oos and r_new_oos["num_trades"] >= MIN_TRADES:
            new_windows.append({
                "period": f"{oos_start.date()}→{oos_end.date()}",
                "best_trend_atr": t_a,
                "best_trans_atr": x_a,
                "oos_ret": r_new_oos["total_return"],
                "oos_sh": r_new_oos["sharpe_ratio"],
                "oos_dd": r_new_oos["max_drawdown"],
                "oos_trades": r_new_oos["num_trades"],
                "oos_pf": r_new_oos["profit_factor"],
                "liqs": r_new_oos["liquidations"],
            })

# ── Print comparison ──
print(f"\n{'='*100}")
print(f"  Walk-Forward: IS={IS_MONTHS}m / OOS={OOS_MONTHS}m / step={STEP_MONTHS}m")
print(f"{'='*100}")

for label, windows, extra_cols in [
    ("2-regime (OLD)", old_windows, ["best_atr"]),
    ("3-regime (NEW)", new_windows, ["best_trend_atr", "best_trans_atr"]),
]:
    if not windows:
        print(f"\n  {label}: No valid windows")
        continue

    pos = sum(1 for w in windows if w["oos_ret"] > 0)
    cum_ret = np.prod([1 + w["oos_ret"] / 100 for w in windows]) - 1
    oos_rets = [w["oos_ret"] for w in windows]
    avg_ret = np.mean(oos_rets)
    med_ret = np.median(oos_rets)
    avg_trades = np.mean([w["oos_trades"] for w in windows])
    total_liqs = sum(w["liqs"] for w in windows)

    print(f"\n── {label} ──")
    print(f"  Windows: {len(windows)} | Positive: {pos}/{len(windows)} ({pos/len(windows)*100:.0f}%)")
    print(f"  Cum OOS: {cum_ret*100:+.2f}% | Avg OOS ret: {avg_ret:+.2f}% | Median OOS ret: {med_ret:+.2f}%")
    print(f"  Avg trades/window: {avg_trades:.0f} | Total liqs: {total_liqs}")
    print(f"\n  {'Period':<22} {'Ret':>8} {'Sharpe':>7} {'DD':>7} {'PF':>6} {'Trades':>6} {'Liq':>4}  Params")
    print(f"  {'-'*90}")
    for w in windows:
        if "best_trend_atr" in w:
            params = f"t={w['best_trend_atr']}x tr={w['best_trans_atr']}x"
        else:
            params = f"atr={w['best_atr']}x"
        print(f"  {w['period']:<22} {w['oos_ret']:>+7.1f}% {w['oos_sh']:>7.3f} {w['oos_dd']:>6.1f}% {w['oos_pf']:>5.2f} {w['oos_trades']:>6} {w['liqs']:>4}  {params}")

    # Verdict
    if pos / len(windows) >= 0.6 and cum_ret > 0:
        verdict = "PASS"
    elif cum_ret > 0:
        verdict = "WARN"
    else:
        verdict = "FAIL"
    print(f"  === {verdict} ===\n")

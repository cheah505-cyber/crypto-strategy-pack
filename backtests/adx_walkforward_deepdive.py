"""Deep-dive each Walk-Forward window: what broke when?"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    load_data,
    compute_signals,
    run_backtest,
)

WINDOW_MONTHS = 6
STEP_MONTHS = 3
MIN_TRADES = 3

ATR_GRID = [1.5, 2.0, 2.5, 3.0]
ADX_GRID = [(30, 20), (25, 20), (30, 15), (25, 15)]


def run_params(df, atr_m, adx_hi, adx_lo):
    """Shallow import patching to test params."""
    import backtests.adx_adaptive_perp_eth_4h as mod

    mod.ATR_TRAIL_MULT = atr_m
    mod.MR_ATR_STOP_MULT = atr_m + 1.0
    mod.ADX_TREND = adx_hi
    mod.ADX_RANGE = adx_lo
    r = mod.run_backtest(df.copy())
    if "error" in r or r["num_trades"] < MIN_TRADES:
        return None
    return r


def market_characterization(df: pd.DataFrame) -> dict:
    """Characterize a period's market regime."""
    c = df["close"]
    ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
    daily_vol = c.pct_change().std() * np.sqrt(365.25 * 6) * 100
    max_peak_to_trough = ((c.cummax() - c) / c.cummax()).max() * 100

    x = np.arange(len(c))
    slope = np.polyfit(x, c.values, 1)[0]
    slope_annualized = (slope / c.iloc[0]) * 365.25 * 6 * 100

    return {
        "return_pct": round(ret, 1),
        "annual_vol": round(daily_vol, 1),
        "max_drawdown": round(max_peak_to_trough, 1),
        "trend_slope_annual": round(slope_annualized, 1),
        "regime": "bull_trend"
        if slope_annualized > 20
        else "bear_trend"
        if slope_annualized < -20
        else "choppy",
    }


def main() -> int:
    df_full = load_data()
    df_full = compute_signals(df_full)

    start_dates = pd.date_range(
        start=df_full.index.min(),
        end=df_full.index.max()
        - pd.DateOffset(months=WINDOW_MONTHS + STEP_MONTHS),
        freq=pd.DateOffset(months=STEP_MONTHS),
    )

    windows = []
    for i, window_start in enumerate(start_dates[:-1]):
        is_start = window_start
        is_end = window_start + pd.DateOffset(months=WINDOW_MONTHS)
        oos_end = is_end + pd.DateOffset(months=STEP_MONTHS)
        if oos_end > df_full.index.max():
            break

        df_is = df_full[
            (df_full.index >= is_start) & (df_full.index < is_end)
        ]
        df_oos = df_full[
            (df_full.index >= is_end) & (df_full.index < oos_end)
        ]
        if len(df_is) < 100 or len(df_oos) < 50:
            continue

        best_sharpe, best_params = -999, None
        for atr_m in ATR_GRID:
            for adx_hi, adx_lo in ADX_GRID:
                if adx_lo >= adx_hi:
                    continue
                r = run_params(df_is, atr_m, adx_hi, adx_lo)
                if r and r["sharpe_ratio"] > best_sharpe:
                    best_sharpe = r["sharpe_ratio"]
                    best_params = (atr_m, adx_hi, adx_lo)

        if best_params is None:
            continue

        atr_m, adx_hi, adx_lo = best_params
        r_oos = run_params(df_oos, atr_m, adx_hi, adx_lo)
        if r_oos is None:
            continue

        mkt = market_characterization(df_oos)

        windows.append(
            {
                "oos_period": f"{str(is_end)[:10]}->{str(oos_end)[:10]}",
                "best_params": f"ATR={atr_m} ADX>{adx_hi}/<{adx_lo}",
                "oos_return": r_oos["total_return"],
                "oos_sharpe": r_oos["sharpe_ratio"],
                "oos_dd": r_oos["max_drawdown"],
                "oos_trades": r_oos["num_trades"],
                "oos_winrate": r_oos["win_rate"],
                "long_trades": r_oos["long_trades"],
                "short_trades": r_oos["short_trades"],
                **mkt,
            }
        )

    print(f"\n{'='*90}")
    print("  WALK-FORWARD DEEP DIVE - Per-Window Analysis")
    print(f"{'='*90}")
    print(
        f"{'OOS Period':<22} {'Mkt Regime':<12} {'Mkt Ret':>8} {'OOS Ret':>8} "
        f"{'Sh':>7} {'DD':>7} {'Win%':>6} {'L/S':>8} {'Best Params':<22}"
    )
    print("-" * 105)
    for w in windows:
        ls = f"{w['long_trades']}/{w['short_trades']}"
        print(
            f"  {w['oos_period']:<20} {w['regime']:<12} {w['return_pct']:>+7.1f}% "
            f"{w['oos_return']:>+7.1f}% {w['oos_sharpe']:>7.3f} {w['oos_dd']:>6.1f}% "
            f"{w['oos_winrate']:>5.1f}% {ls:>8} {w['best_params']:<22}"
        )

    print(f"\n{'='*90}")
    print("  FAILURE PATTERN ANALYSIS")
    print(f"{'='*90}")

    neg_windows = [w for w in windows if w["oos_return"] < 0]
    pos_windows = [w for w in windows if w["oos_return"] > 0]

    print(f"\n  Negative windows: {len(neg_windows)}/{len(windows)}")
    for w in neg_windows:
        print(
            f"    {w['oos_period']}: regime={w['regime']}, "
            f"mkt_ret={w['return_pct']:+.1f}%, strat_ret={w['oos_return']:+.1f}%, "
            f"win_rate={w['oos_winrate']:.1f}%"
        )

    if neg_windows:
        regime_counts = Counter(w["regime"] for w in neg_windows)
        print(f"\n  Failure regime distribution: {dict(regime_counts)}")

    print(f"\n  Positive windows: {len(pos_windows)}/{len(windows)}")
    if pos_windows:
        regime_counts = Counter(w["regime"] for w in pos_windows)
        print(f"  Success regime distribution: {dict(regime_counts)}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

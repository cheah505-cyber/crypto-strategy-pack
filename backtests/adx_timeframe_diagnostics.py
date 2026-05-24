"""Diagnose why ADX Adaptive fails on 1h and daily but works on 4h."""

from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    compute_signals,
    run_backtest,
    print_report,
)


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


ANNUALIZERS = {"1h": np.sqrt(365.25 * 24), "4h": np.sqrt(365.25 * 6), "1d": np.sqrt(365.25)}

def regime_distribution(df: pd.DataFrame, label: str, tf: str = "4h") -> dict:
    """Compute regime distribution: % trend, % range, % transition."""
    trend_pct = df["is_trend"].mean() * 100
    range_pct = df["is_range"].mean() * 100
    transition_pct = 100 - trend_pct - range_pct

    # Signal count
    long_sig = df["long_sig"].sum()
    short_sig = df["short_sig"].sum()

    # Signal quality: average return N bars after entry
    returns = df["close"].pct_change()
    fwd_4 = returns.shift(-4)
    fwd_12 = returns.shift(-12)
    fwd_24 = returns.shift(-24)

    # Hit rate on continuation bars (signal already active), not entry timing.
    # .shift(1).fillna(False) drops the first bar of each signal block where
    # shift produces NaN; this measures "being in a signal" quality.
    long_hitrate_4 = (
        fwd_4[df["long_sig"] & df["long_sig"].shift(1).fillna(False)] > 0
    ).mean()
    short_hitrate_4 = (
        fwd_4[df["short_sig"] & df["short_sig"].shift(1).fillna(False)] < 0
    ).mean()

    return {
        "label": label,
        "bars": len(df),
        "trend_pct": round(trend_pct, 1),
        "range_pct": round(range_pct, 1),
        "transition_pct": round(transition_pct, 1),
        "adx_mean": round(df["adx"].mean(), 1),
        "adx_median": round(df["adx"].median(), 1),
        "rsi_mean": round(df["rsi"].mean(), 1),
        "long_signals": int(long_sig),
        "short_signals": int(short_sig),
        "long_4bar_hitrate": round(long_hitrate_4 * 100, 1)
        if not pd.isna(long_hitrate_4)
        else 0,
        "short_4bar_hitrate": round(short_hitrate_4 * 100, 1)
        if not pd.isna(short_hitrate_4)
        else 0,
        "annual_vol": round(df["close"].pct_change().std() * ANNUALIZERS.get(tf, np.sqrt(365.25 * 6)), 4),
    }


def main() -> int:
    files = {
        "1h": PROJECT_ROOT / "data" / "eth_usdt_1h.csv",
        "4h": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        "1d": PROJECT_ROOT / "data" / "eth_usdt_1d.csv",
    }

    diagnostics = {}
    backtest_results = {}

    for tf, path in files.items():
        if not path.exists():
            print(f"SKIP {tf}: file not found")
            continue

        df = load_csv(str(path))
        df = compute_signals(df)

        diagnostics[tf] = regime_distribution(df, tf, tf=tf)

        # Run backtest
        r = run_backtest(df)
        backtest_results[tf] = r

    # Diagnostic Report
    print(f"\n{'=' * 80}")
    print("  TIMEFRAME DIAGNOSTICS — Why only 4h works?")
    print(f"{'=' * 80}")

    print(f"\n{'Metric':<28} {'1h':>12} {'4h':>12} {'1d':>12}")
    print("-" * 68)
    for key, label in [
        ("bars", "Bars"),
        ("trend_pct", "Trend %"),
        ("range_pct", "Range %"),
        ("transition_pct", "Transition %"),
        ("adx_mean", "ADX mean"),
        ("adx_median", "ADX median"),
        ("rsi_mean", "RSI mean"),
        ("long_signals", "Long signals"),
        ("short_signals", "Short signals"),
        ("annual_vol", "Annual vol"),
        ("long_4bar_hitrate", "Long 4-bar hit rate %"),
        ("short_4bar_hitrate", "Short 4-bar hit rate %"),
    ]:
        vals = "  ".join(
            f"{diagnostics[tf].get(key, 'N/A'):>12}"
            for tf in ["1h", "4h", "1d"]
            if tf in diagnostics
        )
        print(f"  {label:<26} {vals}")

    # Backtest Comparison
    print(f"\n{'Metric':<28} {'1h':>12} {'4h':>12} {'1d':>12}")
    print("-" * 68)
    for key, label in [
        ("total_return", "Total Return %"),
        ("sharpe_ratio", "Sharpe"),
        ("max_drawdown", "Max DD %"),
        ("num_trades", "Trades"),
        ("win_rate", "Win Rate %"),
        ("profit_factor", "Profit Factor"),
    ]:
        vals = "  ".join(
            f"{backtest_results[tf].get(key, 'N/A'):>12}"
            for tf in ["1h", "4h", "1d"]
            if tf in backtest_results
        )
        print(f"  {label:<26} {vals}")

    # Root Cause Analysis
    print(f"\n{'=' * 80}")
    print("  ROOT CAUSE HYPOTHESES")
    print(f"{'=' * 80}")

    diag_1h = diagnostics.get("1h", {})
    diag_4h = diagnostics.get("4h", {})
    diag_1d = diagnostics.get("1d", {})

    # Hypothesis 1: Signal-to-noise ratio differs by timeframe
    if diag_1h and diag_4h:
        print(f"\n  H1 — Signal decay at higher frequency:")
        print(f"    1h long hit rate: {diag_1h.get('long_4bar_hitrate', 0)}%")
        print(f"    4h long hit rate: {diag_4h.get('long_4bar_hitrate', 0)}%")
        if diag_1h.get("long_4bar_hitrate", 0) < 45:
            print(f"    → 1h signals close to random (50% coin flip). Noise dominates.")
        if diag_4h.get("long_4bar_hitrate", 0) > 52:
            print(f"    → 4h signals have detectable edge above noise.")

    # Hypothesis 2: Regime distribution
    print(f"\n  H2 — Regime distribution differs:")
    print(
        f"    1h: {diag_1h.get('trend_pct', 0)}% trend, {diag_1h.get('range_pct', 0)}% range"
    )
    print(
        f"    4h: {diag_4h.get('trend_pct', 0)}% trend, {diag_4h.get('range_pct', 0)}% range"
    )
    print(
        f"    1d: {diag_1d.get('trend_pct', 0)}% trend, {diag_1d.get('range_pct', 0)}% range"
    )

    # Hypothesis 3: Trade frequency
    for tf in ["1h", "4h", "1d"]:
        if tf in backtest_results:
            r = backtest_results[tf]
            if "error" not in r:
                bars = diagnostics[tf]["bars"]
                print(
                    f"\n  H3 — {tf} trade frequency: {r['num_trades']} trades over "
                    f"{bars:,} bars"
                )
                trades_per_month = r["num_trades"] / (bars / (30 * 6))
                print(f"    ~{trades_per_month:.1f} trades/month")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

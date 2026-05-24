"""Run ADX Adaptive on three independent periods to test regime robustness."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    load_data, compute_signals, run_backtest, print_report,
)


def period_report(df: pd.DataFrame, label: str) -> dict:
    """Run backtest on a sub-period. Returns dict or error string."""
    if len(df) < 200:
        return {"error": f"{label}: too few rows ({len(df)})"}
    df = compute_signals(df)
    r = run_backtest(df)
    if "error" in r:
        return {"error": f"{label}: {r['error']}"}
    print(f"\n{'='*60}")
    print(f"  {label}  ({df.index.min().date()} → {df.index.max().date()}, {len(df)} bars)")
    print(f"{'='*60}")
    print_report(r)
    return r


def main() -> int:
    df = load_data()
    print(f"Full data: {df.index.min()} → {df.index.max()}, {len(df)} bars")

    periods = {
        "Bear 2019-2022": ("2019-01-01", "2022-12-31"),
        "Bull 2023-2026": ("2023-01-01", "2026-05-22"),
        "COVID crash Mar-Apr 2020": ("2020-02-15", "2020-04-15"),
        "China ban May-Jul 2021": ("2021-05-01", "2021-07-31"),
        "Luna/3AC collapse May-Jul 2022": ("2022-05-01", "2022-07-31"),
        "FTX collapse Nov-Dec 2022": ("2022-11-01", "2022-12-31"),
    }

    results = {}
    for label, (start, end) in periods.items():
        sub = df[(df.index >= start) & (df.index < end)]
        r = period_report(sub, label)
        results[label] = r

    # Summary table
    print(f"\n{'='*70}")
    print("  CROSS-PERIOD SUMMARY")
    print(f"{'='*70}")
    print(f"{'Period':<30} {'Return':>10} {'Sharpe':>8} {'DD':>8} {'Trades':>7} {'Liqs':>5}")
    print("-" * 70)
    for label, r in results.items():
        if "error" in r:
            print(f"  {label:<28}  ERROR: {r['error']}")
        else:
            print(f"  {label:<28} {r['total_return']:>+9.1f}% {r['sharpe_ratio']:>8.3f} "
                  f"{r['max_drawdown']:>7.1f}% {r['num_trades']:>7} {r['liquidations']:>5}")

    # Verdict
    bear = results.get("Bear 2019-2022", {})
    bull = results.get("Bull 2023-2026", {})
    all_pos = all(
        "error" not in r and r.get("total_return", -999) > 0
        for k, r in results.items()
        if k.startswith(("Bear", "Bull"))
    )

    print()
    if all_pos:
        print("=== PASS: Strategy profitable across bear and bull regimes ===")
    elif "error" not in bear and bear.get("total_return", -999) > 0:
        print("=== PASS: Bear period profitable — regime risk reduced ===")
    else:
        print("=== FAIL: Strategy loses money in bear market — CONFIRMED REGIME OVERFIT ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())

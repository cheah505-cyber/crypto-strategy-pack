"""Run ADX Adaptive Perp on multiple coins to test generalization."""
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


def main() -> int:
    coins = {
        "ETH/USDT": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        "BTC/USDT": PROJECT_ROOT / "data" / "btc_usdt_4h.csv",
    }

    # Add cross-coin files if they exist
    # Note: ADA replaces MATIC which was delisted from Binance in Sep 2024
    for coin in ["SOL/USDT", "BNB/USDT", "ADA/USDT"]:
        slug = coin.replace("/", "_").lower()
        p = PROJECT_ROOT / "data" / f"{slug}_4h.csv"
        if p.exists():
            coins[coin] = p

    results = {}
    for name, path in coins.items():
        print(f"\n{'#'*80}")
        print(f"#  Running ADX Adaptive on {name}")
        print(f"{'#'*80}")
        df = load_csv(str(path))
        df = compute_signals(df)
        r = run_backtest(df)
        results[name] = r
        print_report(r)

    # Cross-Coin Comparison
    print(f"\n{'='*80}")
    print("  CROSS-COIN COMPARISON")
    print(f"{'='*80}")
    header = (
        f"{'Coin':<15} {'Return':>10} {'Sharpe':>8} {'DD':>8} "
        f"{'Trades':>7} {'Exc vs B&H':>12} {'Liqs':>5}"
    )
    print(header)
    print("-" * 75)
    for name, r in results.items():
        if "error" in r:
            print(f"  {name:<13} ERROR: {r['error']}")
        else:
            print(
                f"  {name:<13} {r['total_return']:>+9.1f}% {r['sharpe_ratio']:>8.3f} "
                f"{r['max_drawdown']:>7.1f}% {r['num_trades']:>7} "
                f"{r['excess_return']:>+11.1f}% {r['liquidations']:>5}"
            )

    # Generalization Score
    valid = {k: v for k, v in results.items() if "error" not in v}
    excess_pos = sum(1 for v in valid.values() if v["excess_return"] > 0)
    sharpe_pos = sum(1 for v in valid.values() if v["sharpe_ratio"] > 0)
    sharpe_1plus = sum(1 for v in valid.values() if v["sharpe_ratio"] >= 1.0)
    n = len(valid)

    print(f"\n  Generalization Scorecard ({n} coins):")
    print(f"    Excess return positive: {excess_pos}/{n}")
    print(f"    Sharpe positive:        {sharpe_pos}/{n}")
    print(f"    Sharpe >= 1.0:          {sharpe_1plus}/{n}")
    print(
        f"    Liqs total:             "
        f"{sum(v['liquidations'] for v in valid.values())}"
    )

    if excess_pos >= n * 0.6 and sharpe_pos == n:
        verdict = "PASS: Strategy generalizes across coins"
    elif sharpe_pos >= n * 0.7:
        verdict = (
            "WARN: Positive but with notable outliers "
            "-- coin selection matters"
        )
    else:
        verdict = (
            "FAIL: Strategy is ETH-specific -- "
            "CONFIRMED COIN OVERFIT"
        )

    print(f"\n  === {verdict} ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())

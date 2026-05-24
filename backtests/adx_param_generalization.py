"""Test whether optimal ADX threshold generalizes across assets and timeframes."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    compute_signals, run_backtest,
)
import backtests.adx_adaptive_perp_eth_4h as mod


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


def optimize_adx(
    df_orig: pd.DataFrame, adx_hi_range: list[int], adx_lo_range: list[int]
) -> dict:
    """Grid search ADX thresholds, return best and all results.

    NOTE: Re-runs compute_signals() inside the loop because the signal
    columns (is_trend/is_range) depend on module-level ADX_TREND / ADX_RANGE
    constants. Without this, changing the module attributes has no effect on
    already-computed columns.
    """
    results = []
    for adx_hi in adx_hi_range:
        for adx_lo in adx_lo_range:
            if adx_lo >= adx_hi:
                continue
            mod.ADX_TREND = adx_hi
            mod.ADX_RANGE = adx_lo
            df = compute_signals(df_orig.copy())
            r = run_backtest(df)
            if "error" not in r and r["num_trades"] >= 5:
                results.append({
                    "adx_hi": adx_hi, "adx_lo": adx_lo,
                    "sharpe": r["sharpe_ratio"],
                    "return": r["total_return"],
                    "dd": r["max_drawdown"],
                    "trades": r["num_trades"],
                    "win_rate": r["win_rate"],
                })

    if not results:
        return {"error": "no valid params", "best": None, "all": []}

    results.sort(key=lambda x: x["sharpe"], reverse=True)
    best = results[0]
    return {
        "best_adx_hi": best["adx_hi"],
        "best_adx_lo": best["adx_lo"],
        "best_sharpe": best["sharpe"],
        "best_return": best["return"],
        "best_dd": best["dd"],
        "n_valid": len(results),
        "all": results,
    }


def main() -> int:
    adx_hi_range = [20, 25, 30, 35, 40]
    adx_lo_range = [10, 15, 20, 25]

    configs = {
        "ETH 4h": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        "BTC 4h": PROJECT_ROOT / "data" / "btc_usdt_4h.csv",
        "ETH 1h": PROJECT_ROOT / "data" / "eth_usdt_1h.csv",
        "ETH 1d": PROJECT_ROOT / "data" / "eth_usdt_1d.csv",
    }

    # Add cross-coin if available
    for coin in ["SOL/USDT", "BNB/USDT"]:
        slug = coin.replace("/", "_").lower()
        p = PROJECT_ROOT / "data" / f"{slug}_4h.csv"
        if p.exists():
            configs[f"{coin.split('/')[0]} 4h"] = p

    # Restore defaults before starting
    mod.ADX_TREND = 30
    mod.ADX_RANGE = 20

    print(f"\n{'='*90}")
    print("  PARAMETER GENERALIZATION - Optimal ADX Threshold Per Asset/TF")
    print(f"{'='*90}")
    print(f"{'Config':<15} {'Best ADX':>12} {'Sharpe':>8} {'Return':>10} {'DD':>8} "
          f"{'Trades':>7} {'N Valid':>8}")
    print("-" * 72)

    all_results = {}
    for config_name, path in configs.items():
        if not path.exists():
            continue
        df = load_csv(str(path))
        r = optimize_adx(df, adx_hi_range, adx_lo_range)
        all_results[config_name] = r

        if "error" in r:
            print(f"  {config_name:<13} ERROR: {r['error']}")
        else:
            params = f"ADX>{r['best_adx_hi']}/<{r['best_adx_lo']}"
            print(f"  {config_name:<13} {params:>12} {r['best_sharpe']:>8.3f} "
                  f"{r['best_return']:>+9.1f}% {r['best_dd']:>7.1f}% "
                  f"{r['n_valid']:>7}")

    # Stability Analysis
    valid = {k: v for k, v in all_results.items() if "error" not in v}
    if len(valid) >= 2:
        adx_hi_vals = [v["best_adx_hi"] for v in valid.values()]
        sharpe_vals = [v["best_sharpe"] for v in valid.values()]

        print(f"\n{'='*90}")
        print("  STABILITY ASSESSMENT")
        print(f"{'='*90}")
        print(f"  Optimal ADX trend range: {min(adx_hi_vals)}-{max(adx_hi_vals)} "
              f"(mean={np.mean(adx_hi_vals):.0f}, std={np.std(adx_hi_vals):.0f})")
        print(f"  Best Sharpe range: {min(sharpe_vals):.3f}-{max(sharpe_vals):.3f}")
        print(f"  Configs with Sharpe > 0: {sum(1 for s in sharpe_vals if s > 0)}/{len(valid)}")

        if np.std(adx_hi_vals) > 10:
            print(f"\n  === FAIL: Optimal ADX varies wildly ({np.std(adx_hi_vals):.0f} std) "
                  f"- parameter is overfit to ETH 4h ===")
        elif np.std(adx_hi_vals) > 5:
            print(f"\n  === WARN: Moderate ADX variation ({np.std(adx_hi_vals):.0f} std) "
                  f"- some asset/tf sensitivity ===")
        else:
            print(f"\n  === PASS: ADX threshold stable across assets and timeframes ===")

    # Show full grid for ETH 4h
    if "ETH 4h" in all_results:
        eth_results = all_results["ETH 4h"]
        if "all" in eth_results:
            print(f"\n{'='*90}")
            print("  ETH 4h FULL PARAMETER GRID")
            print(f"{'='*90}")
            print(f"{'ADX Trend':>10} {'ADX Range':>10} {'Sharpe':>8} {'Return':>10} "
                  f"{'DD':>8} {'Trades':>7}")
            print("-" * 55)
            for r in sorted(eth_results["all"], key=lambda x: x["sharpe"], reverse=True)[:15]:
                print(f"  {r['adx_hi']:>10} {r['adx_lo']:>10} {r['sharpe']:>8.3f} "
                      f"{r['return']:>+9.1f}% {r['dd']:>7.1f}% {r['trades']:>7}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

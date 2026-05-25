"""adx-opt-001: ADX>30/<15 cross-coin validation.

Runs the ADX Adaptive strategy with ADX_TREND=30, ADX_RANGE=15
across all 5 coins (ETH, BTC, SOL, BNB, ADA) on 4h timeframe.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests import adx_adaptive_perp_eth_4h as mod


COINS = {
    "ETH/USDT": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
    "BTC/USDT": PROJECT_ROOT / "data" / "btc_usdt_4h.csv",
    "SOL/USDT": PROJECT_ROOT / "data" / "sol_usdt_4h.csv",
    "BNB/USDT": PROJECT_ROOT / "data" / "bnb_usdt_4h.csv",
    "ADA/USDT": PROJECT_ROOT / "data" / "ada_usdt_4h.csv",
}
ADX_HI = 30
ADX_LO = 15
DATA_START = "2023-01-01"
DATA_END = "2026-05-21"
MIN_TRADES = 5


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    df = df.loc[DATA_START:DATA_END].copy()
    return df


def run_coin(
    name: str, path: Path,
) -> dict:
    """Run ADX>30/<15 on a single coin and return results."""
    mod.ADX_TREND = ADX_HI
    mod.ADX_RANGE = ADX_LO

    df = load_csv(path)
    df = mod.compute_signals(df)

    # Reset the cost params in case another run changed them
    mod.FEE = 0.0005  # Binance USDT-M taker 0.05%
    mod.SLIPPAGE = 0.0002
    mod.FUNDING_RATE = 0.0000375
    mod.MAX_LEVERAGE = 10.0
    mod.ATR_TRAIL_MULT = 2.5
    mod.MR_ATR_STOP_MULT = 3.5
    mod.RISK_PER_TRADE = 0.04
    mod.CB_MAX_LOSSES = 5
    mod.CB_COOLDOWN = 24

    r = mod.run_backtest(df)
    if "error" in r:
        return {"coin": name, "error": r["error"], "bars": len(df)}
    if r["num_trades"] < MIN_TRADES:
        return {
            "coin": name, "error": f"only {r['num_trades']} trades",
            "bars": len(df), **r,
        }

    return {"coin": name, "bars": len(df), **r}


def print_cross_table(results: list[dict]) -> str:
    lines = []
    lines.append(f"\n{'='*100}")
    lines.append(f"  ADX>30/<15 CROSS-COIN VALIDATION (4h, {DATA_START} → {DATA_END})")
    lines.append(f"{'='*100}")
    lines.append(
        f"  {'Coin':<10} {'Return%':>8} {'Ann%':>8} {'Sharpe':>7} "
        f"{'DD%':>7} {'Calmar':>7} {'Trades':>6} {'Win%':>6} "
        f"{'PF':>5} {'Bench%':>8} {'Exc%':>8} {'Liqs':>4}"
    )
    lines.append("-" * 100)

    sharpe_vals = []
    for r in results:
        if "error" in r:
            lines.append(f"  {r['coin']:<10} ERROR: {r.get('error', '?')}")
        else:
            exc = f"{r['excess_return']:>+7.1f}%" if "excess_return" in r else "  N/A"
            lines.append(
                f"  {r['coin']:<10} {r['total_return']:>+7.1f}% "
                f"{r['annual_return']:>+7.1f}% {r['sharpe_ratio']:>7.3f} "
                f"{r['max_drawdown']:>6.1f}% {r['calmar_ratio']:>7.3f} "
                f"{r['num_trades']:>6} {r['win_rate']:>5.1f}% "
                f"{r['profit_factor']:>5.2f} {r['benchmark_return']:>+7.1f}% "
                f"{exc} {r.get('liquidations', 0):>4}"
            )
            sharpe_vals.append(r["sharpe_ratio"])

    lines.append("-" * 100)
    if sharpe_vals:
        positives = sum(1 for s in sharpe_vals if s > 0)
        lines.append(
            f"  Summary: {positives}/{len(sharpe_vals)} Sharpe > 0, "
            f"mean Sharpe {np.mean(sharpe_vals):.3f} ± {np.std(sharpe_vals):.3f}"
        )
        lines.append(f"  All Sharpe > 1.0: {'YES' if all(s >= 1.0 for s in sharpe_vals) else 'NO'}")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    print(f"\n{'='*100}")
    print(f"  Task: adx-opt-001 — ADX>30/<15 Cross-Coin Validation")
    print(f"  Config: ADX_TREND={ADX_HI}, ADX_RANGE={ADX_LO}")
    print(f"  Coins: {', '.join(COINS.keys())}")
    print(f"  Data: {DATA_START} → {DATA_END} (4h)")
    print(f"{'='*100}\n")

    results = []
    for name, path in COINS.items():
        if not path.exists():
            logger.warning(f"Skipping {name}: file not found at {path}")
            results.append({"coin": name, "error": "file not found"})
            continue

        logger.info(f"Running {name}...")
        r = run_coin(name, path)
        results.append(r)

        status = "OK" if "error" not in r else f"ERROR: {r['error']}"
        logger.info(f"{name}: {status}")

    table = print_cross_table(results)
    print(table)

    # Write to results dir
    out_dir = PROJECT_ROOT / "loop" / "results" / "adx-opt-001"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / "report.md"
    with open(report_path, "w") as f:
        f.write(table)
    logger.info(f"Report written to {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

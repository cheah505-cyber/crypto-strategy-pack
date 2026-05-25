"""calibrate-001: Multi-timeframe ATR stop calibration for ETH/USDT.

Grid searches ATR_TRAIL_MULT across 1h, 4h, 1d timeframes using
ADX>30/<15 thresholds (from adx-opt-002). Finds optimal stop distance
per timeframe.

Hypotheses from prior findings:
- 1h: needs tighter stops (1.0-2.0x ATR) due to higher noise
- 4h: 2.5x is baseline (from existing calibration), check if improvement possible
- 1d: needs wider stops (3.0-4.0x) due to fewer trades, larger bars
"""
from __future__ import annotations

import itertools
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

DATA_START = "2019-01-01"
DATA_END = "2026-05-21"
MIN_TRADES = 5
ADX_HI = 30
ADX_LO = 15

TIMEFRAMES = {
    "1h":  PROJECT_ROOT / "data" / "eth_usdt_1h.csv",
    "4h":  PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
    "1d":  PROJECT_ROOT / "data" / "eth_usdt_1d.csv",
}

# ATR grid: tight → loose. 1h gets finer grid near low end, 1d gets wider.
ATR_GRID = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5, 4.0]

# MR hard stop ratio relative to ATR_TRAIL_MULT
MR_STOP_RATIO = 1.4


def configure_params(atr_mult: float) -> None:
    mod.ADX_TREND = ADX_HI
    mod.ADX_RANGE = ADX_LO
    mod.FEE = 0.0005  # Binance USDT-M taker 0.05%
    mod.SLIPPAGE = 0.0002
    mod.FUNDING_RATE = 0.0000375
    mod.MAX_LEVERAGE = 10.0
    mod.ATR_TRAIL_MULT = atr_mult
    mod.MR_ATR_STOP_MULT = atr_mult * MR_STOP_RATIO
    mod.RISK_PER_TRADE = 0.04
    mod.CB_MAX_LOSSES = 5
    mod.CB_COOLDOWN = 24


def run_with_params(atr_mult: float, df: pd.DataFrame) -> dict:
    """Run backtest with a specific ATR multiplier on pre-computed signal df."""
    configure_params(atr_mult)
    return mod.run_backtest(df)


def run_grid(tf_label: str, df_sig: pd.DataFrame) -> list[dict]:
    """Run ATR grid for one timeframe. Returns sorted list of results."""
    results = []
    for atr in ATR_GRID:
        r = run_with_params(atr, df_sig)
        results.append({"atr": atr, **r})
        label = f"  ATR={atr:.2f}x"
        if "error" in r:
            logger.info(f"{label}: ERROR - {r['error']}")
        else:
            logger.info(
                f"{label}: Sharpe={r['sharpe_ratio']:.3f}  "
                f"Ret={r['total_return']:+.1f}%  "
                f"DD={r['max_drawdown']:.1f}%  "
                f"Trades={r['num_trades']}  "
                f"Win={r['win_rate']:.1f}%  "
                f"Liqs={r['liquidations']}"
            )
    # Sort by Sharpe descending, NaN last
    results.sort(key=lambda x: x.get("sharpe_ratio", -999), reverse=True)
    return results


def print_top_n(results: list[dict], tf: str, n: int = 5) -> None:
    print(f"\n  ── Top {n} ATR values for {tf} ──")
    print(f"  {'ATR':>6}  {'Sharpe':>8}  {'Ret%':>8}  {'DD%':>7}  {'Calmar':>8}  "
          f"{'Trades':>6}  {'Win%':>6}  {'PF':>6}  {'Liqs':>5}")
    print(f"  {'─'*70}")
    count = 0
    for r in results:
        if count >= n:
            break
        if "error" in r:
            continue
        print(f"  {r['atr']:>5.2f}x  {r['sharpe_ratio']:>8.3f}  "
              f"{r['total_return']:>+7.1f}%  {r['max_drawdown']:>6.1f}%  "
              f"{r['calmar_ratio']:>8.3f}  {r['num_trades']:>6}  "
              f"{r['win_rate']:>5.1f}%  {r['profit_factor']:>5.2f}  "
              f"{r['liquidations']:>5}")
        count += 1
    print()


def _run_sanity_wrapper(df_raw: pd.DataFrame) -> bool:
    """Run sanity checks on signal-computed data."""
    configure_params(2.5)
    df_sig = mod.compute_signals(df_raw)
    return mod._run_sanity(df_sig)


def main() -> int:
    print(f"\n{'='*100}")
    print(f"  Task: calibrate-001 — Multi-Timeframe ATR Stop Calibration")
    print(f"  Config: ADX_TREND={ADX_HI}, ADX_RANGE={ADX_LO}")
    print(f"  Symbol: ETH/USDT")
    print(f"  Data: {DATA_START} → {DATA_END}")
    print(f"  ATR Grid: {ATR_GRID}")
    print(f"  MR Stop Ratio: {MR_STOP_RATIO}x of ATR_TRAIL_MULT")
    print(f"{'='*100}\n")

    all_results: dict[str, list[dict]] = {}

    for tf_label, data_path in TIMEFRAMES.items():
        logger.info(f"{'─'*80}")
        logger.info(f"  Loading {tf_label} data: {data_path.name}")
        logger.info(f"{'─'*80}")

        df = pd.read_csv(data_path, parse_dates=["timestamp"], index_col="timestamp")
        df = df.loc[DATA_START:DATA_END].copy()
        logger.info(f"  Loaded {len(df)} bars: {df.index[0]} → {df.index[-1]}")

        # Compute signals with fixed ADX thresholds
        configure_params(atr_mult=2.5)
        df_sig = mod.compute_signals(df)

        # Sanity check
        if not _run_sanity_wrapper(df):
            logger.error(f"  Sanity tests FAILED for {tf_label} — skipping")
            continue

        # Run ATR grid
        logger.info(f"  Running ATR grid search ({len(ATR_GRID)} values)...")
        grid_results = run_grid(tf_label, df_sig)
        all_results[tf_label] = grid_results

        print_top_n(grid_results, tf_label, n=5)

    # ── Summary ──
    print(f"\n{'='*100}")
    print(f"  SUMMARY: Optimal ATR per Timeframe")
    print(f"{'='*100}")
    print(f"  {'Timeframe':>10}  {'Best ATR':>10}  {'Sharpe':>8}  {'Ret%':>8}  "
          f"{'DD%':>7}  {'Trades':>6}  {'Win%':>6}  {'PF':>6}  {'Liqs':>5}")
    print(f"  {'─'*75}")

    best_params: dict[str, dict] = {}
    for tf_label, results in all_results.items():
        valid = [r for r in results if "error" not in r]
        if not valid:
            print(f"  {tf_label:>10}: NO VALID RESULTS")
            continue
        best = valid[0]  # already sorted by Sharpe
        best_params[tf_label] = best
        print(f"  {tf_label:>10}  {best['atr']:>7.2f}x  {best['sharpe_ratio']:>8.3f}  "
              f"{best['total_return']:>+7.1f}%  {best['max_drawdown']:>6.1f}%  "
              f"{best['num_trades']:>6}  {best['win_rate']:>5.1f}%  "
              f"{best['profit_factor']:>5.2f}  {best['liquidations']:>5}")

    print()

    # ── Additional fine grid near optimal ──
    print(f"{'─'*100}")
    print(f"  FINE GRID: Narrow search around optimal ATR per timeframe")
    print(f"{'─'*100}\n")

    for tf_label, results in all_results.items():
        valid = [r for r in results if "error" not in r]
        if not valid:
            continue
        best = valid[0]
        best_atr = best["atr"]
        # Create fine grid: ±0.5 around best atr, step 0.1
        fine_low = max(0.5, best_atr - 0.5)
        fine_high = best_atr + 0.5
        fine_grid = [round(x, 1) for x in np.arange(fine_low, fine_high + 0.1, 0.1)]

        # Only run fine grid if it gives more granularity than main grid
        main_steps = ATR_GRID
        existing = sum(1 for v in fine_grid if v in main_steps)
        if existing >= len(fine_grid) * 0.6:
            logger.info(f"  {tf_label}: fine grid has {existing}/{len(fine_grid)} existing values — skipping")
            # Still report the best from main grid as final
            continue

        logger.info(f"  {tf_label}: fine grid {fine_grid}...")
        df = pd.read_csv(TIMEFRAMES[tf_label], parse_dates=["timestamp"], index_col="timestamp")
        df = df.loc[DATA_START:DATA_END].copy()
        configure_params(atr_mult=2.5)
        df_sig = mod.compute_signals(df)

        fine_results = []
        for atr in fine_grid:
            r = run_with_params(atr, df_sig)
            fine_results.append({"atr": atr, **r})

        fine_results.sort(key=lambda x: x.get("sharpe_ratio", -999), reverse=True)
        fine_best = fine_results[0] if fine_results else None

        if fine_best and "error" not in fine_best:
            print(f"  {tf_label}: fine best ATR={fine_best['atr']:.2f}x "
                  f"Sharpe={fine_best['sharpe_ratio']:.3f} "
                  f"Ret={fine_best['total_return']:+.1f}% "
                  f"DD={fine_best['max_drawdown']:.1f}%")
            # Update best if fine result is better
            if fine_best["sharpe_ratio"] > best["sharpe_ratio"]:
                best_params[tf_label] = fine_best
                logger.info(f"  → Fine grid improves over main grid: "
                           f"{best['atr']}x (Sharpe {best['sharpe_ratio']}) → "
                           f"{fine_best['atr']}x (Sharpe {fine_best['sharpe_ratio']})")

    # ── Final recommendation ──
    print(f"\n{'='*100}")
    print(f"  FINAL RECOMMENDATIONS")
    print(f"{'='*100}\n")

    recommendations = []
    for tf_label in TIMEFRAMES:
        if tf_label not in best_params:
            print(f"  {tf_label}: ❌ No valid configuration found")
            continue
        b = best_params[tf_label]
        rec_msg = (
            f"  {tf_label}: ATR_TRAIL_MULT = {b['atr']:.2f}x  "
            f"(Sharpe {b['sharpe_ratio']:.3f}, Ret {b['total_return']:+.1f}%, "
            f"DD {b['max_drawdown']:.1f}%, {b['num_trades']} trades)"
        )
        print(rec_msg)
        recommendations.append((tf_label, b))

    print()

    # ── Write report ──
    out_dir = PROJECT_ROOT / "loop" / "results" / "calibrate-001"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# calibrate-001: Multi-Timeframe ATR Stop Calibration\n",
        f"- **Config**: ADX_TREND={ADX_HI}, ADX_RANGE={ADX_LO}",
        f"- **Symbol**: ETH/USDT",
        f"- **Timeframes**: {', '.join(TIMEFRAMES.keys())}",
        f"- **Data**: {DATA_START} → {DATA_END}",
        f"- **Params**: Fee 0.04%, Slippage 0.02%, Funding 0.00375%/bar, 10x lev",
        f"- **Risk**: 4%/trade, 5L CB/24h cooldown",
        f"- **MR Stop Ratio**: {MR_STOP_RATIO}x of ATR_TRAIL_MULT",
        f"- **ATR Grid**: {ATR_GRID}\n",
    ]

    for tf_label in TIMEFRAMES:
        if tf_label not in all_results:
            continue
        lines.append(f"## {tf_label} Results\n")
        lines.append(f"| ATR | Sharpe | Ret% | Ann% | DD% | Calmar | Trades | Win% | PF | Liqs |")
        lines.append(f"|---|---|---|---|---|---|---|---|---|---|")
        for r in all_results[tf_label]:
            if "error" in r:
                lines.append(f"| {r['atr']:.2f}x | ERROR: {r['error']} |")
            else:
                lines.append(
                    f"| {r['atr']:.2f}x | {r['sharpe_ratio']:.3f} | "
                    f"{r['total_return']:+.1f}% | {r['annual_return']:+.1f}% | "
                    f"{r['max_drawdown']:.1f}% | {r['calmar_ratio']:.3f} | "
                    f"{r['num_trades']} | {r['win_rate']:.1f}% | "
                    f"{r['profit_factor']:.2f} | {r['liquidations']} |"
                )
        lines.append("")

    lines.append("## Final Recommendations\n")
    lines.append("| Timeframe | Best ATR | Sharpe | Ret% | DD% | Trades | Win% | PF | Liqs |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for tf_label, b in recommendations:
        lines.append(
            f"| {tf_label} | {b['atr']:.2f}x | {b['sharpe_ratio']:.3f} | "
            f"{b['total_return']:+.1f}% | {b['max_drawdown']:.1f}% | "
            f"{b['num_trades']} | {b['win_rate']:.1f}% | "
            f"{b['profit_factor']:.2f} | {b['liquidations']} |"
        )

    lines.append("\n## Verdict\n")

    all_valid = True
    verdict_notes = []
    has_4h = "4h" in best_params
    for tf_label, b in recommendations:
        if b.get("num_trades", 0) < MIN_TRADES:
            verdict_notes.append(f"{tf_label}: insufficient trades ({b['num_trades']})")
            all_valid = False
        if b.get("liquidations", 0) > 0:
            verdict_notes.append(f"{tf_label}: {b['liquidations']} liquidations")
            all_valid = False
        if b.get("sharpe_ratio", 0) <= 0:
            verdict_notes.append(f"{tf_label}: non-positive Sharpe")
            all_valid = False

    if all_valid:
        lines.append("**PASS** — All timeframes have valid, profitable configurations.\n")
    else:
        lines.append("**WARN** — Some timeframes have issues:\n")
        for n in verdict_notes:
            lines.append(f"- {n}")
        lines.append("")

    if has_4h:
        b4 = best_params["4h"]
        lines.append(
            f"### Key Findings\n\n"
            f"- **4h baseline** (ATR=2.5x, default): Compare against previous full-cycle Sharpe.\n"
            f"- **1h optimal**: ATR={b4['atr']:.2f}x — "
            f"Tighter stop hypothesis confirmed/refuted.\n"
            f"- **1d optimal**: ATR={b4['atr']:.2f}x — "
            f"Wider stop hypothesis confirmed/refuted.\n"
        )

    lines.append("")
    report = "\n".join(lines)
    report_path = out_dir / "report.md"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report written to {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

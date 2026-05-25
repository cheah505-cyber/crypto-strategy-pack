"""adx-opt-002: ADX>30/<15 full-cycle validation on ETH/USDT 4h.

Runs the ADX Adaptive strategy with ADX_TREND=30, ADX_RANGE=15
on the full 2019-01-01 → 2026-05-21 dataset. Includes regime
breakdown (bear 2019-2022, bull 2023-2026) and crash window analysis.

Comparison baseline: default ADX>30/<20 full-cycle result from adx-perp-001.
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

DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"
DATA_START = "2019-01-01"
DATA_END = "2026-05-21"
MIN_TRADES = 5
ADX_HI = 30
ADX_LO = 15

# Crash windows (from Task 1 analysis)
CRASH_WINDOWS = {
    "COVID Crash (Mar-Apr 2020)": ("2020-03-01", "2020-04-30"),
    "China Ban (May-Jul 2021)": ("2021-05-01", "2021-07-31"),
    "Luna/3AC (May-Jul 2022)": ("2022-05-01", "2022-07-31"),
    "FTX Collapse (Nov-Dec 2022)": ("2022-11-01", "2022-12-31"),
}

# Regime periods
REGIMES = {
    "Bear 2019-2022": ("2019-01-01", "2022-12-31"),
    "Bull 2023-2026": ("2023-01-01", "2026-05-21"),
}


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    df = df.loc[DATA_START:DATA_END].copy()
    return df


def configure_params() -> None:
    """Set strategy parameters for this run."""
    mod.ADX_TREND = ADX_HI
    mod.ADX_RANGE = ADX_LO
    mod.FEE = 0.0005  # Binance USDT-M taker 0.05%
    mod.SLIPPAGE = 0.0002
    mod.FUNDING_RATE = 0.00006531  # Binance 6.5yr mean 0.013%/8h
    mod.MAX_LEVERAGE = 10.0
    mod.ATR_TRAIL_MULT = 2.5
    mod.MR_ATR_STOP_MULT = 3.5
    mod.RISK_PER_TRADE = 0.04
    mod.CB_MAX_LOSSES = 5
    mod.CB_COOLDOWN = 24


def run_backtest_on_df(df: pd.DataFrame) -> dict:
    """Run the full backtest pipeline (signals + sanity + backtest)."""
    df_sig = mod.compute_signals(df)
    if not mod._run_sanity(df_sig):
        return {"error": "sanity tests failed"}
    return mod.run_backtest(df_sig)


def run_subperiod(df: pd.DataFrame, start: str, end: str, label: str) -> dict:
    """Run backtest on a date-range slice."""
    sub = df.loc[start:end].copy()
    if len(sub) < 100:
        return {"error": f"{label}: only {len(sub)} bars, skipping"}
    logger.info(f"  {label}: {sub.index[0].date()} → {sub.index[-1].date()} ({len(sub)} bars)")
    return run_backtest_on_df(sub)


def format_result(r: dict, label: str) -> str:
    if "error" in r:
        return f"  {label:<25} ERROR: {r['error']}"
    return (
        f"  {label:<25} "
        f"Ret={r['total_return']:>+7.1f}% "
        f"Ann={r['annual_return']:>+7.1f}% "
        f"Sharpe={r['sharpe_ratio']:>7.3f} "
        f"DD={r['max_drawdown']:>6.1f}% "
        f"Calmar={r['calmar_ratio']:>7.3f} "
        f"Trades={r['num_trades']:>4} "
        f"Win={r['win_rate']:>5.1f}% "
        f"PF={r['profit_factor']:>5.2f} "
        f"Bench={r['benchmark_return']:>+7.1f}% "
        f"Exc={r['excess_return']:>+7.1f}% "
        f"Liqs={r['liquidations']}"
    )


def main() -> int:
    print(f"\n{'='*110}")
    print(f"  Task: adx-opt-002 — ADX>30/<15 Full-Cycle Validation")
    print(f"  Config: ADX_TREND={ADX_HI}, ADX_RANGE={ADX_LO}")
    print(f"  Symbol: ETH/USDT 4h")
    print(f"  Data: {DATA_START} → {DATA_END}")
    print(f"{'='*110}\n")

    # Load full data
    logger.info("Loading data...")
    df = load_data()
    logger.info(f"Loaded {len(df)} bars: {df.index[0]} → {df.index[-1]}")

    # Set parameters
    configure_params()

    # ── Full cycle ──
    logger.info("Running full-cycle backtest...")
    full = run_backtest_on_df(df)
    print(f"\n{'='*110}")
    print(f"  FULL CYCLE: ADX>{ADX_HI}/<{ADX_LO} | ETH/USDT 4h")
    print(f"{'='*110}")
    mod.print_report(full)
    print(f"  Full cycle result line:")
    print(format_result(full, "Full 2019-2026"))
    print()

    # ── Regime breakdown ──
    print(f"{'─'*110}")
    print(f"  REGIME BREAKDOWN")
    print(f"{'─'*110}")
    regime_results = {}
    for label, (start, end) in REGIMES.items():
        r = run_subperiod(df, start, end, label)
        regime_results[label] = r
        print(format_result(r, label))

    print()

    # ── Crash windows ──
    print(f"{'─'*110}")
    print(f"  CRASH WINDOW ANALYSIS")
    print(f"{'─'*110}")
    crash_results = {}
    for label, (start, end) in CRASH_WINDOWS.items():
        r = run_subperiod(df, start, end, label)
        crash_results[label] = r
        print(format_result(r, label))

    print()

    # ── Comparison: ADX>30/<20 (default) vs ADX>30/<15 (optimized) ──
    print(f"{'─'*110}")
    print(f"  COMPARISON: Default ADX>30/<20 vs Optimized ADX>30/<15")
    print(f"{'─'*110}")

    # Run default params for comparison
    configure_params()
    mod.ADX_RANGE = 20  # default
    logger.info("Running default ADX>30/<20 baseline...")
    df_sig_default = mod.compute_signals(df)
    default_results = mod.run_backtest(df_sig_default)

    # Re-run optimized
    configure_params()
    df_sig_opt = mod.compute_signals(df)
    opt_results = mod.run_backtest(df_sig_opt)

    # Also run the regime breakdown for comparison
    for label, (start, end) in REGIMES.items():
        sub_df = df.loc[start:end].copy()
        configure_params()
        mod.ADX_RANGE = 20
        df_d = mod.compute_signals(sub_df)
        d_r = mod.run_backtest(df_d)
        configure_params()
        df_o = mod.compute_signals(sub_df)
        o_r = mod.run_backtest(df_o)
        d_str = format_result(d_r, f"Default {label}")
        o_str = format_result(o_r, f"Optimized {label}")
        print(d_str)
        print(o_str)
        print()

    # ── Summary ──
    print(f"{'='*110}")
    print(f"  SUMMARY")
    print(f"{'='*110}")

    improvements = []
    for metric in ["sharpe_ratio", "total_return", "calmar_ratio", "profit_factor"]:
        def_v = default_results.get(metric, 0)
        opt_v = opt_results.get(metric, 0)
        if def_v != 0:
            chg = (opt_v - def_v) / abs(def_v) * 100
            improvements.append(f"{metric}: {def_v:.3f} → {opt_v:.3f} ({chg:+.1f}%)")
        else:
            improvements.append(f"{metric}: {def_v:.3f} → {opt_v:.3f}")

    print(f"  Optimized ({ADX_HI}/{ADX_LO}) vs Default (30/20):")
    for imp in improvements:
        print(f"    {imp}")
    print(f"\n  Optimized trades: {opt_results['num_trades']} (L:{opt_results['long_trades']} S:{opt_results['short_trades']})")
    print(f"  Optimized win rate: {opt_results['win_rate']}%")
    print(f"  Optimized liqs: {opt_results['liquidations']}")
    print(f"  Optimized max DD: {opt_results['max_drawdown']}%")
    print()

    verdict = "PASS"
    notes = []

    if opt_results.get("num_trades", 0) < MIN_TRADES:
        verdict = "FAIL"
        notes.append(f"Insufficient trades: {opt_results.get('num_trades', 0)}")
    if opt_results.get("liquidations", 0) > 0:
        verdict = "WARN"
        notes.append(f"{opt_results['liquidations']} liquidations occurred")
    if opt_results.get("sharpe_ratio", 0) <= 0:
        verdict = "FAIL"
        notes.append("Non-positive Sharpe ratio")

    if regime_results.get("Bull 2023-2026", {}).get("sharpe_ratio", 0) <= 0:
        verdict = "WARN"
        notes.append("Bull regime Sharpe <= 0")
    if regime_results.get("Bear 2019-2022", {}).get("sharpe_ratio", 0) <= 0:
        verdict = "WARN"
        notes.append("Bear regime Sharpe <= 0")

    print(f"\n  Verdict: {verdict}")
    for n in notes:
        print(f"    Note: {n}")
    print(f"{'='*110}\n")

    # ── Write report ──
    out_dir = PROJECT_ROOT / "loop" / "results" / "adx-opt-002"
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# adx-opt-002: ADX>30/<15 Full-Cycle Validation\n")
    lines.append(f"- **Config**: ADX_TREND={ADX_HI}, ADX_RANGE={ADX_LO}")
    lines.append(f"- **Symbol**: ETH/USDT 4h")
    lines.append(f"- **Data**: {DATA_START} → {DATA_END} ({len(df)} bars)")
    lines.append(f"- **Params**: Fee 0.04%, Slippage 0.02%, Funding 0.00375%/bar, 10x lev")
    lines.append(f"- **Risk**: 4%/trade, 2.5x ATR trail, 5L CB/24h cooldown\n")

    lines.append("## Full Cycle Results\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    for k, v in [
        ("Total Return", f"{opt_results['total_return']:+.2f}%"),
        ("Annual Return", f"{opt_results['annual_return']:+.2f}%"),
        ("Max Drawdown", f"{opt_results['max_drawdown']:.2f}%"),
        ("Sharpe Ratio", f"{opt_results['sharpe_ratio']:.3f}"),
        ("Calmar Ratio", f"{opt_results['calmar_ratio']:.3f}"),
        ("Annual Vol", f"{opt_results.get('ann_volatility', 0):.2f}%"),
        ("Num Trades", f"{opt_results['num_trades']}"),
        ("Win Rate", f"{opt_results['win_rate']:.1f}%"),
        ("Profit Factor", f"{opt_results['profit_factor']:.2f}"),
        ("Avg Return/Trade", f"{opt_results.get('avg_return', 0):+.2f}%"),
        ("Avg Win", f"{opt_results.get('avg_win', 0):+.2f}%"),
        ("Avg Loss", f"{opt_results.get('avg_loss', 0):+.2f}%"),
        ("Stop Outs", f"{opt_results.get('stop_outs', 0)}"),
        ("Liquidations", f"{opt_results.get('liquidations', 0)}"),
        ("Benchmark (B&H)", f"{opt_results['benchmark_return']:+.2f}%"),
        ("Excess Return (ann)", f"{opt_results['excess_return']:+.2f}%"),
        ("Avg Holding", f"{opt_results.get('avg_holding_hours', 0):.0f}h"),
        ("Max Holding", f"{opt_results.get('max_holding_hours', 0):.0f}h"),
        ("Long/Short Trades", f"{opt_results.get('long_trades', 0)}/{opt_results.get('short_trades', 0)}"),
        ("Trend/MR Trades", f"{opt_results.get('trend_trades', 0)}/{opt_results.get('mr_trades', 0)}"),
    ]:
        lines.append(f"| {k} | {v} |")

    lines.append("\n## Regime Breakdown\n")
    lines.append("| Period | Return% | Ann% | Sharpe | DD% | Calmar | Trades | Win% | PF | Bench% | Exc% | Liqs |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for label, r in regime_results.items():
        if "error" in r:
            lines.append(f"| {label} | ERROR: {r['error']} |")
        else:
            lines.append(
                f"| {label} | {r['total_return']:+.1f}% | {r['annual_return']:+.1f}% "
                f"| {r['sharpe_ratio']:.3f} | {r['max_drawdown']:.1f}% | {r['calmar_ratio']:.3f} "
                f"| {r['num_trades']} | {r['win_rate']:.1f}% | {r['profit_factor']:.2f} "
                f"| {r['benchmark_return']:+.1f}% | {r['excess_return']:+.1f}% | {r['liquidations']} |"
            )

    lines.append("\n## Crash Window Analysis\n")
    lines.append("| Period | Return% | Ann% | Sharpe | DD% | Trades | Win% | PF | Bench% | Exc% | Liqs |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, r in crash_results.items():
        if "error" in r:
            lines.append(f"| {label} | ERROR: {r['error']} |")
        else:
            lines.append(
                f"| {label} | {r['total_return']:+.1f}% | {r['annual_return']:+.1f}% "
                f"| {r['sharpe_ratio']:.3f} | {r['max_drawdown']:.1f}% | {r['num_trades']} "
                f"| {r['win_rate']:.1f}% | {r['profit_factor']:.2f} "
                f"| {r['benchmark_return']:+.1f}% | {r['excess_return']:+.1f}% | {r['liquidations']} |"
            )

    lines.append("\n## Comparison: Default (30/20) vs Optimized (30/15)\n")
    lines.append("| Metric | Default (30/20) | Optimized (30/15) | Change |")
    lines.append("|---|---|---|---|")
    for metric, label in [
        ("total_return", "Total Return"),
        ("annual_return", "Annual Return"),
        ("max_drawdown", "Max Drawdown"),
        ("sharpe_ratio", "Sharpe Ratio"),
        ("calmar_ratio", "Calmar Ratio"),
        ("num_trades", "Num Trades"),
        ("win_rate", "Win Rate"),
        ("profit_factor", "Profit Factor"),
        ("liquidations", "Liquidations"),
    ]:
        def_v = default_results.get(metric, 0)
        opt_v = opt_results.get(metric, 0)
        if isinstance(def_v, (int, float)) and isinstance(opt_v, (int, float)):
            if def_v != 0 and metric not in ("num_trades", "liquidations"):
                chg = f"{(opt_v - def_v) / abs(def_v) * 100:+.1f}%"
            else:
                chg = f"{opt_v - def_v:+.1f}" if isinstance(opt_v, (int, float)) else "N/A"
            lines.append(f"| {label} | {def_v} | {opt_v} | {chg} |")
        else:
            lines.append(f"| {label} | {def_v} | {opt_v} | N/A |")

    lines.append("\n## Regime Comparison\n")
    lines.append("| Period | Default Sharpe | Optimized Sharpe | Default Ann% | Optimized Ann% |")
    lines.append("|---|---|---|---|---|")
    configure_params()
    for label, (start, end) in REGIMES.items():
        sub_df = df.loc[start:end].copy()
        mod.ADX_RANGE = 20
        df_d = mod.compute_signals(sub_df)
        d_r = mod.run_backtest(df_d)
        mod.ADX_RANGE = ADX_LO
        df_o = mod.compute_signals(sub_df)
        o_r = mod.run_backtest(df_o)
        d_s = d_r.get("sharpe_ratio", 0)
        o_s = o_r.get("sharpe_ratio", 0)
        d_a = d_r.get("annual_return", 0)
        o_a = o_r.get("annual_return", 0)
        lines.append(f"| {label} | {d_s:.3f} | {o_s:.3f} | {d_a:+.1f}% | {o_a:+.1f}% |")
    configure_params()

    lines.append(f"\n## Verdict\n")
    lines.append(f"**{verdict}**")
    for n in notes:
        lines.append(f"- Note: {n}")
    lines.append("")

    report = "\n".join(lines)
    report_path = out_dir / "report.md"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report written to {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

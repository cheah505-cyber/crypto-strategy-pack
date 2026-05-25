"""Fetch Binance perpetual funding rate history for any symbol.

Usage:
    python tools/fetch_funding_rate.py
    python tools/fetch_funding_rate.py --symbol BTC/USDT:USDT
    python tools/fetch_funding_rate.py --symbol SOL/USDT:USDT --start 2021-01-01
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LIMIT = 1000
MAX_PAGES = 100
PAUSE = 1.0


def infer_pair_label(symbol: str) -> str:
    """ETH/USDT:USDT → ETH, BTC/USDT:USDT → BTC"""
    return symbol.split("/")[0].upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch perpetual funding rate history")
    parser.add_argument("--symbol", default="ETH/USDT:USDT", help="CCXT perpetual symbol (default: ETH/USDT:USDT)")
    parser.add_argument("--start", default="2019-01-01", help="Start date (default: 2019-01-01)")
    args = parser.parse_args()

    symbol = args.symbol
    pair = infer_pair_label(symbol)
    ex = ccxt.binance({"enableRateLimit": True})

    all_rates: list[dict] = []
    since = ex.parse8601(f"{args.start}T00:00:00Z")

    for page in range(MAX_PAGES):
        try:
            rates = ex.fetchFundingRateHistory(symbol, since=since, limit=LIMIT)
            if not rates:
                break
            all_rates.extend(rates)
            last_ts = rates[-1]["timestamp"]
            since = last_ts + 1
            logger.info(f"Page {page + 1}: fetched {len(rates)} records, up to {pd.Timestamp(last_ts, unit='ms').date()}")
            if len(rates) < LIMIT:
                break
            time.sleep(PAUSE)
        except Exception as e:
            logger.warning(f"Page {page + 1} failed: {e}")
            break

    if not all_rates:
        logger.error("No data fetched")
        return 1

    df = pd.DataFrame(all_rates)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.sort_values("timestamp").reset_index(drop=True)

    rates = df["fundingRate"].values

    print(f"\n{'=' * 60}")
    print(f"  Binance {symbol} Perpetual Funding Rate History")
    print(f"{'=' * 60}")
    print(f"  Data range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    print(f"  Total records: {len(df)}")
    print(f"  Time span: {(df['timestamp'].max() - df['timestamp'].min()).days} days")
    print()

    per_8h = rates
    per_4h = rates / 2
    per_1h = rates / 8

    for label, arr in [("8h period", per_8h), ("per 4h bar", per_4h), ("per 1h bar", per_1h)]:
        print(f"  {label}:")
        print(f"    Mean:   {np.mean(arr) * 100:.6f}%")
        print(f"    Median: {np.median(arr) * 100:.6f}%")
        print(f"    Std:    {np.std(arr) * 100:.6f}%")
        print(f"    P1:     {np.percentile(arr, 1) * 100:.6f}%")
        print(f"    P5:     {np.percentile(arr, 5) * 100:.6f}%")
        print(f"    P25:    {np.percentile(arr, 25) * 100:.6f}%")
        print(f"    P75:    {np.percentile(arr, 75) * 100:.6f}%")
        print(f"    P95:    {np.percentile(arr, 95) * 100:.6f}%")
        print(f"    P99:    {np.percentile(arr, 99) * 100:.6f}%")
        print(f"    Min:    {np.min(arr) * 100:.6f}%")
        print(f"    Max:    {np.max(arr) * 100:.6f}%")
        print(f"    Positive:  {np.mean(arr > 0) * 100:.1f}%")
        print(f"    Negative:  {np.mean(arr < 0) * 100:.1f}%")
        print()

    df["month"] = df["timestamp"].dt.to_period("M")
    monthly = df.groupby("month")["fundingRate"].mean() * 100
    print(f"  Monthly average funding rate (top/bottom 5):")
    for m, v in monthly.nlargest(5).items():
        print(f"    {m}: {v:.4f}%")
    print(f"    ...")
    for m, v in monthly.nsmallest(5).items():
        print(f"    {m}: {v:.4f}%")

    # Save to CSV
    csv_name = f"{pair.lower()}_usdt_funding_rate.csv"
    out = Path(__file__).resolve().parent.parent / "data" / csv_name
    df.to_csv(out, index=False)
    logger.info(f"Saved to {out}")

    # Generate constant definitions for this pair
    mean_8h = float(np.mean(per_8h))
    mean_4h = float(np.mean(per_4h))
    mean_1h = float(np.mean(per_1h))
    median_8h = float(np.median(per_8h))

    print(f"\n  ── Add to utils/constants.py ──")
    print(f"  # {pair}/USDT:USDT — Binance {len(df)} records ({df['timestamp'].min().year}-{df['timestamp'].max().year})")
    print(f"  #   mean {mean_8h*100:.6f}%/8h, median {median_8h*100:.6f}%/8h")
    print(f"  FUNDING_RATE_8H_{pair} = {mean_8h:.10f}    # {mean_8h*100:.6f}%/8h")
    print(f"  FUNDING_RATE_4H_{pair} = {mean_4h:.10f}    # {mean_4h*100:.6f}%/4h bar")
    print(f"  FUNDING_RATE_1H_{pair} = {mean_1h:.10f}    # {mean_1h*100:.6f}%/1h bar")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

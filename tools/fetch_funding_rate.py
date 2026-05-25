"""Fetch real Binance ETH/USDT perpetual funding rate history and calculate average."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOL = "ETH/USDT:USDT"  # Binance USDT-M perpetual
LIMIT = 1000  # max per page
MAX_PAGES = 100  # 1000 * 100 = 100k records (~8h*100k = ~900 years, should cover full range)
PAUSE = 1.0  # seconds between pages to avoid rate limit


def main() -> int:
    ex = ccxt.binance({"enableRateLimit": True})

    all_rates: list[dict] = []
    since = ex.parse8601("2019-01-01T00:00:00Z")

    for page in range(MAX_PAGES):
        try:
            rates = ex.fetchFundingRateHistory(SYMBOL, since=since, limit=LIMIT)
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

    # fundingRate from CCXT is already in decimal (e.g., 0.0001 = 0.01%)
    rates = df["fundingRate"].values

    print(f"\n{'=' * 60}")
    print(f"  Binance {SYMBOL} Perpetual Funding Rate History")
    print(f"{'=' * 60}")
    print(f"  Data range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    print(f"  Total records: {len(df)}")
    print(f"  Time span: {(df['timestamp'].max() - df['timestamp'].min()).days} days")
    print()

    # Per-bar conversions (4h bars = 1/2 of funding period, 1h bars = 1/8)
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

    # Time series analysis
    df["month"] = df["timestamp"].dt.to_period("M")
    monthly = df.groupby("month")["fundingRate"].mean() * 100
    print(f"  Monthly average funding rate (top/bottom 5):")
    for m, v in monthly.nlargest(5).items():
        print(f"    {m}: {v:.4f}%")
    print(f"    ...")
    for m, v in monthly.nsmallest(5).items():
        print(f"    {m}: {v:.4f}%")

    # Save to CSV
    out = Path(__file__).resolve().parent.parent / "data" / "eth_usdt_funding_rate.csv"
    df.to_csv(out, index=False)
    logger.info(f"Saved to {out}")

    # Recommended values for constants
    print(f"\n  Recommended constants:")
    mean_4h = np.mean(per_4h)
    print(f"    FUNDING_RATE_4H = {mean_4h:.10f}  # {mean_4h*100:.6f}%/4h bar")
    median_4h = np.median(per_4h)
    print(f"    (Median: {median_4h:.10f} = {median_4h*100:.6f}%/4h)")
    print()
    print(f"  Current strategy uses:")
    print(f"    FUNDING_RATE = 0.0000375  # 0.00375%/4h bar (0.0225%/8h)")
    print(f"    vs real mean:   {mean_4h*100:.6f}%/4h ({mean_4h*2*100:.6f}%/8h)")
    print(f"    vs real median: {median_4h*100:.6f}%/4h ({median_4h*2*100:.6f}%/8h)")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

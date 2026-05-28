"""Fetch latest ETH/USDT 4h bars from Binance, append to existing CSV.
Used by GitHub Actions signal pipeline. No API key needed (public OHLCV).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_ohlcv import get_exchange, fetch_since, candles_to_df

DATA_DIR = PROJECT_ROOT / "data"
SYMBOL = "ETH/USDT"
TIMEFRAME = "4h"
CSV = DATA_DIR / "eth_usdt_4h.csv"


def main() -> int:
    # Determine since timestamp from existing CSV
    if CSV.exists():
        existing = pd.read_csv(CSV, parse_dates=["timestamp"], index_col="timestamp")
        if existing.index.tz is None:
            existing.index = existing.index.tz_localize("UTC")
        last_ts = existing.index.max()
        since_ms = int(last_ts.timestamp() * 1000) + 1  # +1ms to avoid duplicate
        print(f"Existing data ends at {last_ts}, fetching since then...")
    else:
        since_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
        existing = pd.DataFrame()
        print("No existing data, fetching from 2019...")

    exchange = get_exchange()
    exchange.load_markets()

    candles = fetch_since(SYMBOL, TIMEFRAME, since_ms, exchange)
    if not candles:
        print("No new bars available")
        return 0

    new_df = candles_to_df(candles)
    print(f"Fetched {len(new_df)} new bars: {new_df.index[0]} → {new_df.index[-1]}")

    if not existing.empty:
        df = pd.concat([existing, new_df]).drop_duplicates().sort_index()
    else:
        df = new_df

    df.to_csv(CSV)
    print(f"Saved {len(df)} total bars to {CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

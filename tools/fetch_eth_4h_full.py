"""Fetch ETH/USDT 4h data 2019-2022 from Binance, append to existing file."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_ohlcv import get_exchange, fetch_since, candles_to_df

DATA_DIR = PROJECT_ROOT / "data"


def main() -> int:
    exchange = get_exchange()
    exchange.load_markets()

    since_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    candles = fetch_since("ETH/USDT", "4h", since_ms, exchange)
    df = candles_to_df(candles)

    # Only keep data before 2023 (existing data covers 2023+)
    df = df[df.index < "2023-01-01"]

    if df.empty:
        print("No new data fetched (already have 2019-2022)")
        return 0

    # Read existing and merge
    existing_path = DATA_DIR / "eth_usdt_4h.csv"
    if existing_path.exists():
        existing = pd.read_csv(existing_path, parse_dates=["timestamp"], index_col="timestamp")
        df = pd.concat([df, existing]).drop_duplicates().sort_index()

    df.to_csv(existing_path)
    print(f"Merged {len(df)} rows, range: {df.index.min()} → {df.index.max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

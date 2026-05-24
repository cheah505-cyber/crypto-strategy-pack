"""Fetch 4h data for SOL, BNB, POL (was MATIC) from Binance."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_ohlcv import get_exchange, fetch_since, candles_to_df

# Note: MATIC was delisted and replaced by POL on Binance in Sep 2024.
# POL/USDT only has data since Feb 2025 (insufficient). Using ADA/USDT instead.
TARGETS = [
    ("SOL/USDT", "2019-01-01"),
    ("BNB/USDT", "2019-01-01"),
    ("ADA/USDT", "2019-01-01"),
]


def main() -> int:
    exchange = get_exchange()
    exchange.load_markets()

    for symbol, since_date in TARGETS:
        symbol_slug = symbol.replace("/", "_").lower()
        out_path = PROJECT_ROOT / "data" / f"{symbol_slug}_4h.csv"

        if symbol not in exchange.markets:
            print(f"SKIP {symbol}: not found on Binance")
            continue

        since_ms = int(pd.Timestamp(since_date, tz="UTC").timestamp() * 1000)
        print(f"Fetching {symbol} 4h since {since_date}...")
        candles = fetch_since(symbol, "4h", since_ms, exchange)
        df = candles_to_df(candles)
        df.to_csv(out_path)
        print(f"  Saved {len(df)} rows to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

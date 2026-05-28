"""Fetch latest ETH/USDT 4h bars from Binance, append to existing CSV.
Used by GitHub Actions signal pipeline. No API key needed (public OHLCV).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

import ccxt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
SYMBOL = "ETH/USDT"
TIMEFRAME = "4h"
CSV = DATA_DIR / "eth_usdt_4h.csv"

# Exchanges to try in order (many geo-block GitHub Actions IPs)
EXCHANGES = [
    lambda: ccxt.okx({"enableRateLimit": True, "timeout": 30000}),
    lambda: ccxt.kucoin({"enableRateLimit": True, "timeout": 30000}),
    lambda: ccxt.bybit({"enableRateLimit": True, "timeout": 30000, "options": {"defaultType": "spot"}}),
    lambda: ccxt.binance({"enableRateLimit": True, "timeout": 30000, "options": {"defaultType": "spot"}}),
]


def fetch_ohlcv_bars(exchange, symbol: str, timeframe: str, since_ms: int, limit: int = 1000) -> list:
    """Fetch OHLCV bars with pagination, returns list of [ts,o,h,l,c,v]."""
    all_candles = []
    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        if not candles:
            break
        all_candles.extend(candles)
        if len(candles) < limit:
            break
        since_ms = candles[-1][0] + 1
        if len(all_candles) >= 5000:
            break
    return all_candles


def candles_to_df(candles: list) -> pd.DataFrame:
    """Convert CCXT candles to DataFrame."""
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def main() -> int:
    # Determine since timestamp from existing CSV
    if CSV.exists():
        existing = pd.read_csv(CSV, parse_dates=["timestamp"], index_col="timestamp")
        if existing.index.tz is None:
            existing.index = existing.index.tz_localize("UTC")
        last_ts = existing.index.max()
        since_ms = int(last_ts.timestamp() * 1000) + 1
        print(f"Existing data ends at {last_ts}, fetching since then...")
    else:
        since_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
        existing = pd.DataFrame()
        print("No existing data, fetching from 2019...")

    candles = []
    for factory in EXCHANGES:
        try:
            exchange = factory()
            candles = fetch_ohlcv_bars(exchange, SYMBOL, TIMEFRAME, since_ms)
            if candles:
                print(f"OK: {exchange.id}")
                break
            print(f"No new bars from {exchange.id}")
        except Exception as e:
            print(f"FAIL: {exchange.id} — {e}")
            continue

    if not candles:
        print("All exchanges failed or no new bars available")
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

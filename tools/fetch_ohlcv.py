"""从 Binance 拉取 OHLCV 数据，支持分页和断点续传。

Usage:
    python fetch_ohlcv.py --symbol ETH/USDT --timeframe 1h --since 2023-01-01
    python fetch_ohlcv.py --symbol ETH/USDT --timeframe 1h --since 2023-01-01 --append
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

BINANCE_RATE_LIMIT = 1200  # 有 API key 的权重限制
BINANCE_OHLCV_WEIGHT = 2   # 每次 fetch_ohlcv 消耗的权重
REQUEST_DELAY = 0.25       # 请求间隔秒数（保守）


def get_exchange() -> ccxt.Exchange:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_SECRET", "")
    # 只用公共端点 - 拉 OHLCV 不需要 API Key，且 API Key 会触发受限 SAPI 调用
    config: dict = {
        "enableRateLimit": True, "timeout": 30000,
        "options": {"defaultType": "spot"},
    }
    logger.info("使用公共端点获取 OHLCV 数据")
    return ccxt.binance(config)


def fetch_since(
    symbol: str,
    timeframe: str,
    since_ms: int,
    exchange: ccxt.Exchange,
) -> list[list]:
    """分页拉取全部 K 线数据。"""
    all_candles: list[list] = []
    current_since = since_ms
    total_fetched = 0
    request_count = 0

    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=1000)
            request_count += 1
        except ccxt.RateLimitExceeded as e:
            logger.warning(f"触碰到频率限制，等待 5s... {e}")
            time.sleep(5)
            continue
        except ccxt.NetworkError as e:
            logger.warning(f"网络错误，等待 3s 后重试... {e}")
            time.sleep(3)
            continue

        if not candles:
            logger.info(f"无更多数据，结束。总请求 {request_count} 次")
            break

        if len(all_candles) > 0 and candles[0][0] <= all_candles[-1][0]:
            # 去重：跳过已获取的时间点
            last_ts = all_candles[-1][0]
            candles = [c for c in candles if c[0] > last_ts]

        if not candles:
            break

        all_candles.extend(candles)
        total_fetched = len(all_candles)

        # 更新下次请求的起始点
        current_since = candles[-1][0] + 1

        latest_dt = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
        logger.info(
            f"已拉取 {total_fetched:>6} 根 K 线 | 最新: {latest_dt.strftime('%Y-%m-%d %H:%M')} UTC"
            f" | 请求 #{request_count}"
        )

        time.sleep(REQUEST_DELAY)

    return all_candles


def candles_to_df(candles: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="timestamp").set_index("timestamp").sort_index()
    return df


def save_data(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    symbol_slug = symbol.replace("/", "_").lower()
    out_path = DATA_DIR / f"{symbol_slug}_{timeframe}.csv"
    df.to_csv(out_path)
    logger.info(f"数据已保存: {out_path} ({len(df)} 行)")
    return out_path


def load_existing(path: Path) -> pd.DataFrame | None:
    """加载已有数据文件（断点续传用）。"""
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    logger.info(f"加载已有数据: {path} ({len(df)} 行)")
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Binance 拉取 OHLCV 数据")
    parser.add_argument("--symbol", default="ETH/USDT", help="交易对")
    parser.add_argument("--timeframe", default="1h", help="K 线周期 (1m, 5m, 1h, 4h, 1d)")
    parser.add_argument("--since", default="2023-01-01", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--append", action="store_true", help="追加到已有文件（断点续传）")
    args = parser.parse_args()

    since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ms = int(since_dt.timestamp() * 1000)

    exchange = get_exchange()
    exchange.load_markets()

    if args.symbol not in exchange.markets:
        logger.error(f"交易对 {args.symbol} 在 Binance 上不存在")
        return 1

    symbol_slug = args.symbol.replace("/", "_").lower()
    out_path = DATA_DIR / f"{symbol_slug}_{args.timeframe}.csv"

    existing_df: pd.DataFrame | None = None
    if args.append:
        existing_df = load_existing(out_path)
        if existing_df is not None and not existing_df.empty:
            last_ts = existing_df.index.max()
            since_ms = int(last_ts.timestamp() * 1000) + 1
            logger.info(f"断点续传模式: 从 {last_ts} 继续")

    logger.info(f"开始拉取 {args.symbol} {args.timeframe} 从 {args.since}")
    candles = fetch_since(args.symbol, args.timeframe, since_ms, exchange)
    new_df = candles_to_df(candles)

    if existing_df is not None and not existing_df.empty:
        df = pd.concat([existing_df, new_df]).drop_duplicates().sort_index()
        logger.info(f"合并后总计: {len(df)} 行")
    else:
        df = new_df

    if df.empty:
        logger.error("未获取到任何数据")
        return 1

    save_data(df, args.symbol, args.timeframe)

    start_dt = df.index.min().strftime("%Y-%m-%d %H:%M UTC")
    end_dt = df.index.max().strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n数据范围: {start_dt} → {end_dt}")
    print(f"总行数: {len(df):,}")
    print(f"列: {list(df.columns)}")
    print(f"缺失值: {df.isnull().sum().sum()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

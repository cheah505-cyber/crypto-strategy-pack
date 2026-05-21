"""OHLCV 数据质量检查器

对接《数据质量检查-量化与足球数据.md》规范，输出 DQS 评分。

Usage:
    python ohlcv_quality_checker.py --file data.csv --symbol BTC/USDT
    python ohlcv_quality_checker.py --file data.csv --format json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_data(path: str, symbol: str | None = None) -> pd.DataFrame:
    """加载 CSV，标准化列名，设置时间索引。"""
    df = pd.read_csv(
        path,
        parse_dates=["timestamp", "datetime", "date"],
        infer_datetime_format=True,
    )
    # 标准化列名
    rename_map = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    # 设置时间索引
    time_col = next((c for c in ("timestamp", "datetime", "date") if c in df.columns), None)
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], utc=True)
        df = df.set_index(time_col).sort_index()
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    return df


def check_ohlc_logic(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """检查 OHLC 逻辑一致性。返回 (违规数, 违规行)。"""
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        logger.warning("缺少 OHLC 列，跳过逻辑检查")
        return 0, pd.DataFrame()
    mask = (df["high"] >= df[["open", "close", "low"]].max(axis=1)) & (
        df["low"] <= df[["open", "close", "high"]].min(axis=1)
    )
    violations = df[~mask]
    return len(violations), violations


def check_timestamp_continuity(df: pd.DataFrame, freq: str = "1h") -> tuple[int, list]:
    """检查时间戳连续性。返回 (缺失数, 缺失时间点列表)。"""
    expected = pd.date_range(start=df.index.min(), end=df.index.max(), freq=freq)
    missing = expected.difference(df.index)
    return len(missing), missing.tolist()


def check_future_leakage(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """检查时间戳是否包含未来时间。"""
    now = pd.Timestamp.now(tz="UTC")
    future = df[df.index > now]
    return len(future), future


def check_price_jumps(df: pd.DataFrame, threshold_sigma: float = 5.0) -> tuple[int, pd.DataFrame]:
    """检测价格异常跳变（收益率绝对值超过 N 倍标准差）。"""
    if "close" not in df.columns:
        return 0, pd.DataFrame()
    returns = df["close"].pct_change().dropna()
    if returns.empty:
        return 0, pd.DataFrame()
    mean, std = returns.mean(), returns.std()
    mask = returns.abs() > mean + threshold_sigma * std
    jumps = df.loc[mask.index[mask]]
    return len(jumps), jumps


def check_volume_anomaly(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """检测成交量突变（单日成交量 / 20 日均量 > 10 或 < 0.01）。"""
    if "volume" not in df.columns:
        return 0, pd.DataFrame()
    vol_ma = df["volume"].rolling(window=20, min_periods=1).mean()
    ratio = df["volume"] / vol_ma.replace(0, pd.NA)
    mask = (ratio > 10) | (ratio < 0.01)
    anomalies = df[mask]
    return len(anomalies), anomalies


def check_zero_volume(df: pd.DataFrame) -> tuple[int, pd.DataFrame]:
    """标记零成交量行。"""
    if "volume" not in df.columns:
        return 0, pd.DataFrame()
    zeros = df[df["volume"] == 0]
    return len(zeros), zeros


def calculate_dqs(df: pd.DataFrame, results: dict) -> dict:
    """计算五维度 DQS 评分。"""
    total = len(df)
    if total == 0:
        return {"total": 0, "overall": 0, "dimensions": {}}

    # 完整性：空值率
    null_rate = df.isnull().mean().mean()
    completeness = max(0, 100 - null_rate * 100)

    # 一致性：OHLC 逻辑 + 类型合规
    ohlc_violations = results.get("ohlc_violations", 0)
    consistency = max(0, 100 - (ohlc_violations / total) * 100)

    # 有效性：价格跳变 + 成交量异常
    jump_rate = results.get("price_jumps", 0) / total
    vol_rate = results.get("volume_anomalies", 0) / total
    validity = max(0, 100 - (jump_rate + vol_rate) * 100)

    # 唯一性：重复时间戳
    dup_rate = df.index.duplicated().sum() / total
    uniqueness = max(0, 100 - dup_rate * 100)

    # 时效性：未来数据 + 缺失时间点
    future_rate = results.get("future_rows", 0) / total
    missing_rate = results.get("missing_timestamps", 0) / total if total > 1 else 0
    timeliness = max(0, 100 - (future_rate + min(missing_rate, 1.0)) * 100)

    overall = (
        completeness * 0.30
        + consistency * 0.25
        + validity * 0.20
        + uniqueness * 0.15
        + timeliness * 0.10
    )

    return {
        "total_rows": total,
        "overall": round(overall, 1),
        "grade": "🟢" if overall >= 85 else "🟡" if overall >= 65 else "🔴",
        "dimensions": {
            "completeness": round(completeness, 1),
            "consistency": round(consistency, 1),
            "validity": round(validity, 1),
            "uniqueness": round(uniqueness, 1),
            "timeliness": round(timeliness, 1),
        },
    }


def run_checks(df: pd.DataFrame, freq: str = "1h") -> dict:
    """运行全部检查，返回结果字典。"""
    results: dict = {}

    logger.info("检查 OHLC 逻辑一致性...")
    ohlc_count, ohlc_rows = check_ohlc_logic(df)
    results["ohlc_violations"] = ohlc_count
    if ohlc_count:
        logger.warning(f"发现 {ohlc_count} 行 OHLC 逻辑违规")

    logger.info("检查时间戳连续性...")
    missing_count, missing_times = check_timestamp_continuity(df, freq)
    results["missing_timestamps"] = missing_count
    if missing_count:
        logger.warning(f"发现 {missing_count} 个缺失时间点")

    logger.info("检查未来数据泄露...")
    future_count, future_rows = check_future_leakage(df)
    results["future_rows"] = future_count
    if future_count:
        logger.error(f"🔴 发现 {future_count} 行未来数据！必须修复后方可使用")

    logger.info("检测价格跳变...")
    jump_count, jump_rows = check_price_jumps(df)
    results["price_jumps"] = jump_count
    if jump_count:
        logger.warning(f"发现 {jump_count} 个价格异常跳变")

    logger.info("检测成交量异常...")
    vol_count, vol_rows = check_volume_anomaly(df)
    results["volume_anomalies"] = vol_count
    if vol_count:
        logger.warning(f"发现 {vol_count} 个成交量异常")

    logger.info("标记零成交量...")
    zero_count, zero_rows = check_zero_volume(df)
    results["zero_volume"] = zero_count
    if zero_count:
        logger.info(f"发现 {zero_count} 行零成交量")

    results["dqs"] = calculate_dqs(df, results)
    return results


def print_report(results: dict, df: pd.DataFrame) -> None:
    """打印文本报告。"""
    dqs = results["dqs"]
    print(f"\n{'='*50}")
    print(f"OHLCV 数据质量检查报告")
    print(f"{'='*50}")
    print(f"总行数: {dqs['total_rows']}")
    print(f"DQS 评分: {dqs['overall']}/100 {dqs['grade']}")
    print(f"\n五维度评分:")
    for dim, score in dqs["dimensions"].items():
        print(f"  {dim:15s}: {score}")
    print(f"\n问题汇总:")
    print(f"  OHLC 逻辑违规: {results['ohlc_violations']}")
    print(f"  缺失时间点:    {results['missing_timestamps']}")
    print(f"  未来数据行:    {results['future_rows']} {'🔴' if results['future_rows'] else ''}")
    print(f"  价格异常跳变:  {results['price_jumps']}")
    print(f"  成交量异常:    {results['volume_anomalies']}")
    print(f"  零成交量:      {results['zero_volume']}")
    print(f"\n建议:")
    if dqs["overall"] >= 85:
        print("  🟢 数据质量良好，可进入回测")
    elif dqs["overall"] >= 65:
        print("  🟡 数据可用，但需记录注意事项")
    else:
        print("  🔴 数据质量不达标，修复后方可使用")
    print(f"{'='*50}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="OHLCV 数据质量检查器")
    parser.add_argument("--file", required=True, help="CSV 文件路径")
    parser.add_argument("--symbol", help="筛选特定交易对")
    parser.add_argument("--freq", default="1h", help="时间频率 (1m, 5m, 1h, 1d)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--out", help="输出文件路径（json 格式时有效）")
    args = parser.parse_args()

    if not Path(args.file).exists():
        logger.error(f"文件不存在: {args.file}")
        return 1

    df = load_data(args.file, args.symbol)
    logger.info(f"加载数据: {len(df)} 行, 列: {list(df.columns)}")

    results = run_checks(df, freq=args.freq)

    if args.format == "json":
        output = json.dumps(results, indent=2, default=str)
        if args.out:
            Path(args.out).write_text(output, encoding="utf-8")
            logger.info(f"报告已保存: {args.out}")
        else:
            print(output)
    else:
        print_report(results, df)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""因子权重优化器 — 指数时间衰减 + 平滑因子

基于执行历史动态调整多因子组合权重，近期表现好的因子权重提升，
老因子逐步衰减。支持与前次权重平滑过渡。

Usage:
    python factor_weight_optimizer.py --file factor_performance.csv
    python factor_weight_optimizer.py --file factor_performance.csv --previous weights.json --alpha 0.3
    python factor_weight_optimizer.py --file factor_performance.csv --metric sharpe --half-life 30

Input CSV Format (wide):
    date,momentum_ic,value_ic,volatility_ic,size_ic
    2024-01-01,0.05,-0.02,0.03,0.01
    2024-01-02,0.03,0.01,-0.01,0.02

Output:
    JSON 权重配置文件 + 可选写入 Obsidian
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class FactorWeightOptimizer:
    """因子权重优化器。"""

    def __init__(
        self,
        half_life_days: float = 60.0,
        smoothing_alpha: float = 0.3,
        quality_weight: float = 0.7,
        usage_weight: float = 0.3,
        min_weight: float = 0.05,
        metric: str = "ic",
    ):
        self.half_life_days = half_life_days
        self.decay_lambda = math.log(2) / half_life_days
        self.smoothing_alpha = smoothing_alpha
        self.quality_weight = quality_weight
        self.usage_weight = usage_weight
        self.min_weight = min_weight
        self.metric = metric

    def calculate_decay(self, days_ago: float) -> float:
        """计算时间衰减因子：Decay = e^(-λt)。"""
        return math.exp(-self.decay_lambda * days_ago)

    def load_performance(self, path: str) -> pd.DataFrame:
        """加载因子表现数据。"""
        df = pd.read_csv(path, parse_dates=["date"])
        df = df.set_index("date").sort_index()
        return df

    def load_previous_weights(self, path: str | None) -> pd.Series | None:
        """加载历史权重配置。"""
        if path is None or not Path(path).exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        weights = data.get("weights", {})
        if not weights:
            return None
        return pd.Series(weights)

    def compute_weights(self, df: pd.DataFrame, previous: pd.Series | None = None) -> pd.Series:
        """计算优化后的因子权重。"""
        now = df.index.max()
        factor_cols = [c for c in df.columns if c != self.metric and not c.endswith("_weight")]

        records: list[dict[str, Any]] = []
        for col in factor_cols:
            series = df[col].dropna()
            if series.empty:
                continue

            weighted_sum = 0.0
            decay_sum = 0.0
            for dt, val in series.items():
                days_ago = (now - pd.Timestamp(dt)).total_seconds() / 86400.0
                decay = self.calculate_decay(days_ago)
                weighted_sum += float(val) * decay
                decay_sum += decay

            avg_quality = weighted_sum / decay_sum if decay_sum > 0 else 0.0
            usage_freq = len(series) / len(df) if len(df) > 0 else 0.0
            raw_weight = self.quality_weight * avg_quality + self.usage_weight * usage_freq

            records.append(
                {
                    "factor": col,
                    "avg_quality": avg_quality,
                    "usage_freq": usage_freq,
                    "raw_weight": raw_weight,
                }
            )

        weights_df = pd.DataFrame(records).set_index("factor")

        # 归一化到 0-1
        max_w = weights_df["raw_weight"].max()
        if max_w and max_w != 0:
            weights_df["normalized"] = weights_df["raw_weight"] / max_w
        else:
            weights_df["normalized"] = 0.0

        # 应用平滑
        if previous is not None and not previous.empty:
            for factor in weights_df.index:
                if factor in previous.index:
                    old = previous[factor]
                    new = weights_df.loc[factor, "normalized"]
                    weights_df.loc[factor, "smoothed"] = (
                        1 - self.smoothing_alpha
                    ) * new + self.smoothing_alpha * old
                else:
                    weights_df.loc[factor, "smoothed"] = weights_df.loc[
                        factor, "normalized"
                    ]
        else:
            weights_df["smoothed"] = weights_df["normalized"]

        # 裁剪最小权重并重新归一化
        weights_df["final"] = weights_df["smoothed"].clip(lower=self.min_weight)
        total = weights_df["final"].sum()
        if total > 0:
            weights_df["final"] = weights_df["final"] / total

        return weights_df["final"].sort_values(ascending=False)

    def save_weights(
        self,
        weights: pd.Series,
        changes: pd.Series,
        metadata: dict[str, Any],
        out_dir: Path,
    ) -> Path:
        """保存权重到 JSON。"""
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = out_dir / f"factor_weights_{timestamp}.json"
        latest_path = out_dir / "factor_weights_latest.json"

        data = {
            "generated_at": datetime.now().isoformat(),
            "version": "1.0.0",
            "weights": weights.to_dict(),
            "changes": changes.to_dict(),
            "metadata": metadata,
        }

        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("权重已保存: %s", filepath)
        return filepath

    def run(
        self,
        perf_path: str,
        prev_weights_path: str | None = None,
        out_dir: Path | None = None,
    ) -> dict[str, Any]:
        """执行完整优化流程。"""
        if out_dir is None:
            out_dir = Path(__file__).parent.parent / "data" / "weights"

        logger.info("加载因子表现数据: %s", perf_path)
        df = self.load_performance(perf_path)
        logger.info("数据范围: %s 至 %s, %d 行, 因子: %s", df.index.min(), df.index.max(), len(df), list(df.columns))

        previous = self.load_previous_weights(prev_weights_path)
        if previous is not None:
            logger.info("加载历史权重: %d 个因子", len(previous))

        logger.info("计算权重 (半衰期=%.0f天, 平滑因子=%.2f)...", self.half_life_days, self.smoothing_alpha)
        weights = self.compute_weights(df, previous)

        changes = pd.Series({f: 0.0 for f in weights.index})
        if previous is not None:
            for factor in weights.index:
                old = previous.get(factor, 0.0)
                changes[factor] = round(weights[factor] - old, 4)

        metadata = {
            "half_life_days": self.half_life_days,
            "smoothing_alpha": self.smoothing_alpha,
            "quality_weight": self.quality_weight,
            "min_weight": self.min_weight,
            "period_days": (df.index.max() - df.index.min()).days,
            "total_records": len(df),
        }

        filepath = self.save_weights(weights, changes, metadata, out_dir)

        # 打印摘要
        print(f"\n{'='*50}")
        print("因子权重优化结果")
        print(f"{'='*50}")
        print(f"数据区间: {df.index.min().date()} ~ {df.index.max().date()}")
        print(f"半衰期: {self.half_life_days} 天")
        print(f"平滑因子: {self.smoothing_alpha}")
        print(f"\n优化后权重 (Top 10):")
        for factor, weight in weights.head(10).items():
            change = changes.get(factor, 0.0)
            direction = "↑" if change > 0 else "↓" if change < 0 else "→"
            print(f"  {direction} {factor:20s}: {weight:.4f} (变化: {change:+.4f})")
        print(f"{'='*50}\n")

        return {
            "status": "success",
            "file_path": str(filepath),
            "weights": weights.to_dict(),
            "changes": changes.to_dict(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="因子权重优化器")
    parser.add_argument("--file", required=True, help="因子表现 CSV 路径 (wide format)")
    parser.add_argument("--previous", help="历史权重 JSON 路径")
    parser.add_argument("--metric", default="ic", help="评估指标列名前缀")
    parser.add_argument("--half-life", type=float, default=60.0, help="时间衰减半衰期 (天)")
    parser.add_argument("--alpha", type=float, default=0.3, help="平滑因子 (0-1)")
    parser.add_argument("--quality-weight", type=float, default=0.7, help="质量分权重")
    parser.add_argument("--min-weight", type=float, default=0.05, help="最小权重阈值")
    parser.add_argument("--out-dir", help="输出目录 (默认: ../data/weights/)")
    args = parser.parse_args()

    if not Path(args.file).exists():
        logger.error("文件不存在: %s", args.file)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else None

    optimizer = FactorWeightOptimizer(
        half_life_days=args.half_life,
        smoothing_alpha=args.alpha,
        quality_weight=args.quality_weight,
        min_weight=args.min_weight,
        metric=args.metric,
    )

    result = optimizer.run(args.file, args.previous, out_dir)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

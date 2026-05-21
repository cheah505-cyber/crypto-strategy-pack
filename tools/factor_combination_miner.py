"""频繁因子组合挖掘器 — Apriori 算法

从历史回测记录中挖掘经常同时有效的因子组合，识别高收益的成功模式
和低收益的失败模式。

Usage:
    python factor_combination_miner.py --file factor_combinations.csv
    python factor_combination_miner.py --file factor_combinations.csv --min-support 0.08 --min-confidence 0.65
    python factor_combination_miner.py --file factor_combinations.csv --quality-metric sharpe --threshold 1.0

Input CSV Format:
    date,momentum,value,volatility,size,return,sharpe
    2024-01-01,1,1,0,0,0.02,1.2
    2024-01-01,1,0,1,0,-0.01,0.5
    2024-01-02,0,1,1,1,0.03,1.8

    (因子列为 0/1，表示该组合是否包含此因子)

Output:
    JSON 模式报告 (成功模式 / 失败模式 / 频繁项集)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class FactorCombinationMiner:
    """因子组合挖掘器，基于 Apriori 算法。"""

    def __init__(
        self,
        min_support: float = 0.1,
        min_confidence: float = 0.6,
        max_length: int = 4,
        quality_threshold: float = 0.8,
        failure_threshold: float = 0.4,
        quality_metric: str = "sharpe",
    ):
        self.min_support = min_support
        self.min_confidence = min_confidence
        self.max_length = max_length
        self.quality_threshold = quality_threshold
        self.failure_threshold = failure_threshold
        self.quality_metric = quality_metric

    def load_data(self, path: str) -> pd.DataFrame:
        """加载因子组合历史数据。"""
        df = pd.read_csv(path, parse_dates=["date"])
        return df

    def extract_transactions(self, df: pd.DataFrame) -> list[tuple[frozenset[str], float]]:
        """从 DataFrame 提取交易记录：[(因子集合, 质量分数), ...]。"""
        # 自动识别因子列（0/1 格式的列）
        factor_cols = []
        for col in df.columns:
            if col in ("date", self.quality_metric, "return"):
                continue
            unique_vals = df[col].dropna().unique()
            if set(unique_vals).issubset({0, 1, 0.0, 1.0}):
                factor_cols.append(col)

        if not factor_cols:
            raise ValueError("未检测到 0/1 格式的因子列，请检查输入 CSV")

        logger.info("识别到 %d 个因子: %s", len(factor_cols), factor_cols)

        transactions = []
        for _, row in df.iterrows():
            items = {col for col in factor_cols if row[col] == 1 or row[col] == 1.0}
            quality = float(row.get(self.quality_metric, 0.0))
            transactions.append((frozenset(items), quality))

        return transactions

    def _apriori_gen(self, prev_itemsets: list[frozenset[str]], k: int) -> set[frozenset[str]]:
        """生成候选 k-项集（连接步 + 剪枝步）。"""
        candidates: set[frozenset[str]] = set()
        n = len(prev_itemsets)
        for i in range(n):
            for j in range(i + 1, n):
                union = prev_itemsets[i] | prev_itemsets[j]
                if len(union) == k:
                    candidates.add(union)

        # 剪枝：所有 (k-1)-子集必须都是频繁的
        frequent_subsets = set(prev_itemsets)
        pruned: set[frozenset[str]] = set()
        for candidate in candidates:
            subsets = [frozenset(s) for s in combinations(candidate, k - 1)]
            if all(subset in frequent_subsets for subset in subsets):
                pruned.add(candidate)
        return pruned

    def find_frequent_itemsets(
        self, transactions: list[tuple[frozenset[str], float]]
    ) -> dict[int, list[tuple[frozenset[str], int]]]:
        """运行 Apriori 算法，返回各级频繁项集。"""
        itemsets = [items for items, _ in transactions]
        n = len(itemsets)
        min_count = max(1, int(self.min_support * n))

        # L1: 频繁 1-项集
        item_counts = Counter()
        for items in itemsets:
            for item in items:
                item_counts[item] += 1

        l1 = [(frozenset([item]), count) for item, count in item_counts.items() if count >= min_count]
        all_frequent: dict[int, list[tuple[frozenset[str], int]]] = {1: l1}

        current_l = [itemset for itemset, _ in l1]
        k = 2
        while current_l and k <= self.max_length:
            candidates = self._apriori_gen(current_l, k)
            candidate_counts = defaultdict(int)
            for items in itemsets:
                for candidate in candidates:
                    if candidate.issubset(items):
                        candidate_counts[candidate] += 1

            current_l = [itemset for itemset, count in candidate_counts.items() if count >= min_count]
            if current_l:
                all_frequent[k] = [(itemset, candidate_counts[itemset]) for itemset in current_l]
                k += 1

        return all_frequent

    def identify_success_patterns(
        self,
        transactions: list[tuple[frozenset[str], float]],
        frequent_itemsets: dict[int, list[tuple[frozenset[str], int]]],
    ) -> list[dict[str, Any]]:
        """识别高收益的成功模式。"""
        n = len(transactions)
        success_patterns = []

        for length, itemsets in frequent_itemsets.items():
            for itemset, count in itemsets:
                matching = [q for items, q in transactions if itemset.issubset(items)]
                if not matching:
                    continue

                avg_quality = sum(matching) / len(matching)
                if avg_quality >= self.quality_threshold:
                    success_rate = sum(1 for q in matching if q >= self.quality_threshold) / len(matching)
                    pattern = {
                        "factors": sorted(list(itemset)),
                        "length": length,
                        "support": round(count / n, 4),
                        "occurrence_count": count,
                        "avg_quality": round(avg_quality, 4),
                        "success_rate": round(success_rate, 4),
                        "sample_size": len(matching),
                    }
                    success_patterns.append(pattern)

        success_patterns.sort(key=lambda x: x["avg_quality"], reverse=True)
        return success_patterns

    def identify_failure_patterns(
        self,
        transactions: list[tuple[frozenset[str], float]],
        frequent_itemsets: dict[int, list[tuple[frozenset[str], int]]],
    ) -> list[dict[str, Any]]:
        """识别低收益的失败模式（反模式）。"""
        n = len(transactions)
        failure_patterns = []

        for length, itemsets in frequent_itemsets.items():
            for itemset, count in itemsets:
                matching = [q for items, q in transactions if itemset.issubset(items)]
                if not matching:
                    continue

                avg_quality = sum(matching) / len(matching)
                if avg_quality < self.failure_threshold:
                    failure_rate = sum(1 for q in matching if q < self.failure_threshold) / len(matching)
                    pattern = {
                        "factors": sorted(list(itemset)),
                        "length": length,
                        "support": round(count / n, 4),
                        "avg_quality": round(avg_quality, 4),
                        "failure_rate": round(failure_rate, 4),
                        "sample_size": len(matching),
                    }
                    failure_patterns.append(pattern)

        failure_patterns.sort(key=lambda x: x["failure_rate"], reverse=True)
        return failure_patterns

    def discover(
        self,
        path: str,
        days: int = 365,
        out_dir: Path | None = None,
    ) -> dict[str, Any]:
        """执行完整挖掘流程。"""
        if out_dir is None:
            out_dir = Path(__file__).parent.parent / "data" / "patterns"
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info("加载数据: %s", path)
        df = self.load_data(path)

        # 时间过滤
        cutoff = df["date"].max() - timedelta(days=days)
        df = df[df["date"] >= cutoff]
        logger.info("分析区间: %s 至 %s, %d 条记录", df["date"].min().date(), df["date"].max().date(), len(df))

        transactions = self.extract_transactions(df)
        logger.info("提取 %d 条交易记录", len(transactions))

        logger.info("运行 Apriori (min_support=%.2f, max_length=%d)...", self.min_support, self.max_length)
        frequent_itemsets = self.find_frequent_itemsets(transactions)
        total_frequent = sum(len(itemsets) for itemsets in frequent_itemsets.values())
        logger.info("发现 %d 个频繁项集", total_frequent)

        logger.info("识别成功模式 (quality >= %.2f)...", self.quality_threshold)
        success = self.identify_success_patterns(transactions, frequent_itemsets)
        logger.info("发现 %d 个成功模式", len(success))

        logger.info("识别失败模式 (quality < %.2f)...", self.failure_threshold)
        failure = self.identify_failure_patterns(transactions, frequent_itemsets)
        logger.info("发现 %d 个失败模式", len(failure))

        result = {
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start_date": df["date"].min().strftime("%Y-%m-%d"),
                "end_date": df["date"].max().strftime("%Y-%m-%d"),
                "days": days,
                "total_records": len(df),
            },
            "parameters": {
                "min_support": self.min_support,
                "min_confidence": self.min_confidence,
                "max_length": self.max_length,
                "quality_threshold": self.quality_threshold,
                "failure_threshold": self.failure_threshold,
                "quality_metric": self.quality_metric,
            },
            "success_patterns": success[:20],
            "failure_patterns": failure[:20],
            "statistics": {
                "total_frequent_itemsets": total_frequent,
                "success_patterns_count": len(success),
                "failure_patterns_count": len(failure),
            },
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = out_dir / f"factor_patterns_{timestamp}.json"
        latest_path = out_dir / "factor_patterns_latest.json"

        filepath.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        latest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("报告已保存: %s", filepath)

        # 打印摘要
        print(f"\n{'='*50}")
        print("因子组合挖掘报告")
        print(f"{'='*50}")
        print(f"数据区间: {df['date'].min().date()} ~ {df['date'].max().date()}")
        print(f"频繁项集总数: {total_frequent}")
        print(f"\n成功模式 Top 5 (按 {self.quality_metric} 排序):")
        for i, p in enumerate(success[:5], 1):
            factors = " + ".join(p["factors"])
            print(f"  {i}. {factors:30s} 支持度={p['support']:.3f} 平均{self.quality_metric}={p['avg_quality']:.3f}")
        if failure:
            print(f"\n失败模式 Top 3:")
            for i, p in enumerate(failure[:3], 1):
                factors = " + ".join(p["factors"])
                print(f"  {i}. {factors:30s} 支持度={p['support']:.3f} 平均{self.quality_metric}={p['avg_quality']:.3f}")
        print(f"{'='*50}\n")

        return {
            "status": "success",
            "file_path": str(filepath),
            "success_count": len(success),
            "failure_count": len(failure),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="频繁因子组合挖掘器 (Apriori)")
    parser.add_argument("--file", required=True, help="因子组合历史 CSV 路径")
    parser.add_argument("--days", type=int, default=365, help="分析最近 N 天 (默认: 365)")
    parser.add_argument("--min-support", type=float, default=0.1, help="最小支持度 (0-1)")
    parser.add_argument("--min-confidence", type=float, default=0.6, help="最小置信度 (0-1)")
    parser.add_argument("--max-length", type=int, default=4, help="最大项集长度")
    parser.add_argument("--quality-threshold", type=float, default=0.8, help="成功模式质量阈值")
    parser.add_argument("--failure-threshold", type=float, default=0.4, help="失败模式质量阈值")
    parser.add_argument("--quality-metric", default="sharpe", help="质量指标列名 (sharpe / return / ic)")
    parser.add_argument("--out-dir", help="输出目录 (默认: ../data/patterns/)")
    args = parser.parse_args()

    if not Path(args.file).exists():
        logger.error("文件不存在: %s", args.file)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else None

    miner = FactorCombinationMiner(
        min_support=args.min_support,
        min_confidence=args.min_confidence,
        max_length=args.max_length,
        quality_threshold=args.quality_threshold,
        failure_threshold=args.failure_threshold,
        quality_metric=args.quality_metric,
    )

    result = miner.discover(args.file, args.days, out_dir)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

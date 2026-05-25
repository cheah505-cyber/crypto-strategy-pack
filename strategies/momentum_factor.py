"""ETH/USDT 动量因子计算 + 时间序列 IC 分析。

Usage:
    python -m strategies.momentum_factor
    python -m strategies.momentum_factor --lookback 24 48 96
    python -m strategies.momentum_factor --output json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_1h.csv"
RESULTS_PATH = PROJECT_ROOT / "results"


def load_data(path: str | Path | None = None) -> pd.DataFrame:
    path = Path(path) if path else DATA_PATH
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
    logger.info(f"加载数据: {len(df):,} 行, {df.index.min()} → {df.index.max()}")
    return df


# ── 因子计算 ──────────────────────────────────────────────


def roc(df: pd.DataFrame, period: int = 24) -> pd.Series:
    """Rate of Change: (close[t] / close[t-N] - 1) * 100."""
    return (df["close"] / df["close"].shift(period) - 1) * 100


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing)."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """MACD histogram: MACD line - signal line."""
    ema_fast = df["close"].ewm(span=fast, min_periods=slow).mean()
    ema_slow = df["close"].ewm(span=slow, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
    return macd_line - signal_line


def channel_breakout(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """价格在 N 期通道中的位置 0-100。100 = 突破上轨, 0 = 跌破下轨。"""
    high_n = df["high"].rolling(period).max()
    low_n = df["low"].rolling(period).min()
    rng = high_n - low_n
    return ((df["close"] - low_n) / rng.replace(0, np.nan)) * 100


def vol_adj_momentum(df: pd.DataFrame, period: int = 24, vol_period: int = 48) -> pd.Series:
    """波动率调整动量: ROC / 滚动收益率标准差。"""
    ret = df["close"].pct_change()
    raw_mom = df["close"] / df["close"].shift(period) - 1
    vol = ret.rolling(vol_period).std()
    return (raw_mom / vol.replace(0, np.nan)) * 100


def sma_ratio(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """双均线比: fast_SMA / slow_SMA - 1。正值 = 短期趋势向上。"""
    sma_fast = df["close"].rolling(fast).mean()
    sma_slow = df["close"].rolling(slow).mean()
    return (sma_fast / sma_slow - 1) * 100


def volume_momentum(df: pd.DataFrame, period: int = 24) -> pd.Series:
    """量价共振: ROC * 成交量变化率。正 = 放量上涨，负 = 放量下跌。"""
    price_mom = roc(df, period)
    vol_change = df["volume"] / df["volume"].shift(period) - 1
    return price_mom * (1 + vol_change)


# ── 新增因子: 布林带 ──────────────────────────────────────


def bollinger_b(df: pd.DataFrame, window: int = 20, std_mult: float = 2.0) -> pd.Series:
    """布林带 %b: 价格在通道中的位置。

    %b = (close - lower) / (upper - lower)
    0 = 下轨, 1 = 上轨, 0.5 = 中轨。
    低于 0 = 超卖（均值回归做多信号）, 高于 1 = 超买（均值回归做空信号）。
    """
    sma = df["close"].rolling(window).mean()
    std = df["close"].rolling(window).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    return (df["close"] - lower) / (upper - lower).replace(0, np.nan)


# ── 新增因子: K线形态 ─────────────────────────────────────


def candlestick_composite(df: pd.DataFrame, _dummy: int = 0) -> pd.Series:
    """K线形态复合分数（单K线几何特征）。

    基于蜡烛几何形状的连续分数：
    - 正 = 看涨信号（长下影线 + 小实体 → 多头拒绝下跌）
    - 负 = 看跌信号（长上影线 + 小实体 → 空头拒绝上涨）
    - 大实体 = 动量延续（方向为符号）
    - 十字星 = 中性（小幅反转倾向）
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = c - o
    body_abs = body.abs()
    total_range = (h - l).replace(0, np.nan)

    # 上下影线
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

    upper_ratio = upper_wick / total_range
    lower_ratio = lower_wick / total_range
    body_ratio = body_abs / total_range

    # 拒绝信号：长下影线 → 看涨（正），长上影线 → 看跌（负）
    rejection = lower_ratio - upper_ratio

    # 十字星：小实体 → 市场犹豫，反转倾向（按方向加权）
    is_doji = body_ratio < 0.15
    doji_signal = is_doji.astype(float) * rejection  # 十字星的方向看影线

    # 动量实体：大实体方向
    momentum = body / df["close"].shift(1) * 100

    # 加权复合
    return rejection * 0.3 + doji_signal * 0.3 + momentum * 0.4


def candlestick_doji(df: pd.DataFrame, threshold: float = 0.15) -> pd.Series:
    """十字星检测：|open-close| / (high-low) < threshold。

    0 = 非十字星, 1 = 十字星。
    十字星出现在趋势后 → 潜在反转。
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body_ratio = (c - o).abs() / (h - l).replace(0, np.nan)
    return (body_ratio < threshold).astype(float)


def candlestick_hammer(df: pd.DataFrame, _dummy: int = 0) -> pd.Series:
    """锤子线 / 吊人线 检测。

    正 = 锤子线（下跌后出现，看涨反转）
    负 = 吊人线（上涨后出现，看跌反转）
    连续值表示形态强度。
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    total_range = (h - l).replace(0, np.nan)
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

    # 锤子线特征：下影线 ≥ 2× 实体，上影线很小
    hammer = ((lower_wick >= 2 * body) & (upper_wick <= 0.3 * body)).astype(float)

    # 吊人线特征：上影线 ≥ 2× 实体，下影线很小
    hanging = ((upper_wick >= 2 * body) & (lower_wick <= 0.3 * body)).astype(float)

    return hammer - hanging


# ── 新增因子: 成交量背离 ──────────────────────────────────


def volume_divergence_roc(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """量价背离（rate-of-change 方法）。

    比较价格 ROC 和成交量 ROC 的方向一致性。
    正 = 看涨背离（价格下跌但成交量萎缩 → 抛压衰竭）
    负 = 看跌背离（价格上涨但成交量萎缩 → 上涨乏力）
    """
    price_roc = roc(df, period)
    vol_roc = df["volume"] / df["volume"].shift(period) - 1

    # 价跌量缩（抛压衰竭）= 看涨背离
    # price_roc < 0 且 vol_roc < 0 时, 乘积为正
    return price_roc * vol_roc


def volume_divergence_corr(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """量价背离（滚动相关系数方法）。

    价格变化与成交量变化的滚动相关系数。
    负值 = 价格与成交量反向运动 = 背离。
    正 = 量价齐升（趋势健康）, 负 = 量价分歧（潜在反转）。
    """
    price_ret = df["close"].pct_change()
    vol_change = df["volume"].pct_change()
    corr = price_ret.rolling(window).corr(vol_change)
    # -corr: 负相关系数 → 正背离信号
    return -corr * 100


FACTOR_REGISTRY = {
    "roc": roc,
    "rsi": rsi,
    "macd": macd,
    "channel_breakout": channel_breakout,
    "vol_adj_momentum": vol_adj_momentum,
    "sma_ratio": sma_ratio,
    "volume_momentum": volume_momentum,
    "bollinger_b": bollinger_b,
    "candlestick_composite": candlestick_composite,
    "candlestick_doji": candlestick_doji,
    "candlestick_hammer": candlestick_hammer,
    "volume_divergence_roc": volume_divergence_roc,
    "volume_divergence_corr": volume_divergence_corr,
}

DEFAULT_LOOKBACKS = {
    "roc": [12, 24, 48, 96],
    "rsi": [7, 14, 21],
    "macd": [(8, 21, 5), (12, 26, 9), (20, 50, 12)],
    "channel_breakout": [10, 20, 50],
    "vol_adj_momentum": [(12, 48), (24, 48), (48, 96)],
    "sma_ratio": [(10, 30), (20, 50), (50, 200)],
    "volume_momentum": [12, 24, 48],
    "bollinger_b": [(20, 2.0), (20, 2.5), (50, 2.0), (50, 2.5)],
    "candlestick_composite": [0],
    "candlestick_doji": [0.1, 0.15, 0.2],
    "candlestick_hammer": [0],
    "volume_divergence_roc": [12, 24, 48],
    "volume_divergence_corr": [14, 20, 40],
}


# ── IC 分析 ───────────────────────────────────────────────


def compute_ic(
    df: pd.DataFrame,
    factor_name: str,
    lookback: int | tuple,
    forward_periods: int = 1,
    ic_window: int = 168,
) -> dict:
    """计算单个因子组合的 IC 统计量。

    Args:
        df: OHLCV DataFrame
        factor_name: FACTOR_REGISTRY 中的因子名
        lookback: 因子参数
        forward_periods: 前瞻期数（1 = 下一根 K 线）
        ic_window: 滚动 IC 窗口（默认 168 = 一周的 1h K 线）

    Returns:
        dict: IC 均值、ICIR、hit_rate、p 值、效应量、IC 时间序列
    """
    fn = FACTOR_REGISTRY[factor_name]
    args = lookback if isinstance(lookback, tuple) else (lookback,)
    factor = fn(df, *args)

    # 前瞻收益：close[t+1] / close[t] - 1
    fwd_return = df["close"].pct_change(periods=forward_periods).shift(-forward_periods)

    # 对齐：因子在 t 时刻，收益在 t→t+1
    aligned = pd.DataFrame({"factor": factor, "fwd_return": fwd_return}).dropna()
    if len(aligned) < 100:
        return {"error": f"有效数据点不足 ({len(aligned)}), 需 ≥100"}

    # 滚动 IC
    rolling_ic = aligned["factor"].rolling(ic_window).corr(aligned["fwd_return"])

    ic_series = rolling_ic.dropna()
    if len(ic_series) < 50:
        return {"error": f"滚动 IC 窗不足 ({len(ic_series)}), 需 ≥50"}

    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std())
    icir = ic_mean / ic_std if ic_std > 0 else 0.0
    hit_rate = float((ic_series > 0).mean())

    # t-test: H0: IC mean = 0
    t_stat, p_value = stats.ttest_1samp(ic_series, 0.0)
    p_value = float(p_value)

    # Cohen's d (效应量) = mean / std
    cohens_d = abs(ic_mean) / ic_std if ic_std > 0 else 0.0

    # 置信区间
    n = len(ic_series)
    se = ic_std / np.sqrt(n)
    ci_low = ic_mean - 1.96 * se
    ci_high = ic_mean + 1.96 * se

    label = format_factor_label(factor_name, lookback)

    return {
        "factor": label,
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "icir": round(icir, 4),
        "hit_rate": round(hit_rate, 4),
        "p_value": round(p_value, 6),
        "cohens_d": round(cohens_d, 4),
        "ci_95": (round(ci_low, 4), round(ci_high, 4)),
        "n_obs": n,
        "ic_series": ic_series,
    }


def format_factor_label(name: str, lookback: int | tuple) -> str:
    if isinstance(lookback, tuple):
        return f"{name}{lookback}"
    return f"{name}_{lookback}"


def classify_result(r: dict) -> str:
    """分类因子结果。"""
    if "error" in r:
        return "FAIL invalid"
    if r["p_value"] < 0.05 and abs(r["ic_mean"]) > 0.02 and r["icir"] > 0.3:
        return "PASS valid"
    if r["p_value"] < 0.10 and abs(r["ic_mean"]) > 0.01:
        return "WARN marginal"
    return "FAIL not-signif"


def run_all_factors(
    df: pd.DataFrame,
    forward_periods: int = 1,
    ic_window: int = 168,
) -> list[dict]:
    """跑全部因子 × 全部参数组合。"""
    results: list[dict] = []
    for name, lookbacks in DEFAULT_LOOKBACKS.items():
        for lb in lookbacks:
            r = compute_ic(df, name, lb, forward_periods, ic_window)
            r["verdict"] = classify_result(r)
            results.append(r)

    results.sort(key=lambda x: abs(x.get("ic_mean", 0)), reverse=True)
    return results


# ── 分层回测 ──────────────────────────────────────────────


def stratified_backtest(
    df: pd.DataFrame,
    factor_name: str,
    lookback: int | tuple,
    n_groups: int = 5,
    forward_periods: int = 1,
) -> dict:
    """按因子值分层，看各组收益是否单调。"""
    fn = FACTOR_REGISTRY[factor_name]
    args = lookback if isinstance(lookback, tuple) else (lookback,)
    factor = fn(df, *args)
    fwd_return = df["close"].pct_change(periods=forward_periods).shift(-forward_periods)

    aligned = pd.DataFrame({"factor": factor, "fwd_return": fwd_return}).dropna()
    aligned["group"] = pd.qcut(aligned["factor"], n_groups, labels=False, duplicates="drop")

    grouped = aligned.groupby("group")["fwd_return"].agg(["mean", "std", "count"])
    grouped["ann_return"] = grouped["mean"] * 8760  # 年化（1h × 8760）
    grouped["ann_vol"] = grouped["std"] * np.sqrt(8760)
    grouped["sharpe"] = grouped["ann_return"] / grouped["ann_vol"].replace(0, np.nan)

    bottom = grouped.iloc[0] if len(grouped) > 0 else None
    top = grouped.iloc[-1] if len(grouped) > 0 else None

    label = format_factor_label(factor_name, lookback)
    logger.info(
        f"{label} 分层回测: Q1(低)={bottom['ann_return']:.4f} → "
        f"Q{n_groups}(高)={top['ann_return']:.4f}"
    )

    return {
        "factor": label,
        "groups": grouped.to_dict(),
        "long_short_spread": float(top["ann_return"] - bottom["ann_return"])
        if bottom is not None and top is not None
        else 0.0,
    }


# ── 报告输出 ──────────────────────────────────────────────


def print_report(results: list[dict]) -> None:
    print(f"\n{'='*80}")
    print("ETH/USDT 1h Momentum Factor IC Analysis")
    print(f"{'='*80}")
    print(f"{'Factor':<28} {'ICmean':>8} {'ICIR':>7} {'Hit%':>7} {'p-val':>8} {'CohenD':>8} {'Verdict'}")
    print("-" * 80)

    valid_count = 0
    marginal_count = 0
    for r in results:
        if "error" in r:
            continue
        verdict_icon = r["verdict"].split()[0]
        print(
            f"{r['factor']:<28} {r['ic_mean']:>+8.4f} {r['icir']:>7.3f} "
            f"{r['hit_rate']:>6.1%} {r['p_value']:>8.4f} {r['cohens_d']:>8.3f} {r['verdict']}"
        )
        if "PASS" in r["verdict"]:          valid_count += 1
        elif "WARN" in r["verdict"]:        marginal_count += 1

    print("-" * 80)
    print(f"Total: {len(results)} combos | PASS: {valid_count} | WARN: {marginal_count} | FAIL: {len(results) - valid_count - marginal_count}")
    print(f"{'='*80}\n")


def save_results(results: list[dict], path: str | Path | None = None) -> Path:
    import json

    if path is None:
        RESULTS_PATH.mkdir(exist_ok=True)
        path = RESULTS_PATH / "momentum_ic_results.json"

    serializable = []
    for r in results:
        d = {k: v for k, v in r.items() if k != "ic_series"}
        d["ic_series"] = r.get("ic_series", pd.Series(dtype=float)).tolist() if "ic_series" in r else []
        d["ci_95"] = list(d.get("ci_95", (0, 0)))
        serializable.append(d)

    Path(path).write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")
    logger.info(f"结果已保存: {path}")
    return Path(path)


# ── CLI ───────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="ETH/USDT 动量因子 IC 分析")
    parser.add_argument("--data", help="数据文件路径 (默认 data/eth_usdt_1h.csv)")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    parser.add_argument("--forward", type=int, default=1, help="前瞻期数 (默认 1)")
    parser.add_argument("--ic-window", type=int, default=168, help="滚动 IC 窗口 (默认 168)")
    args = parser.parse_args()

    df = load_data(args.data)
    results = run_all_factors(df, forward_periods=args.forward, ic_window=args.ic_window)

    if args.output == "json":
        out_path = save_results(results)
        print(out_path)
    else:
        print_report(results)

    return 0


def run_stratification(df: pd.DataFrame, top_n: int = 5) -> None:
    """对 IC 最强的因子跑分层回测。"""
    results = run_all_factors(df)
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda x: abs(x["ic_mean"]), reverse=True)

    print(f"\n{'='*80}")
    print("ETH/USDT 1h Stratified Backtest (Top Factors)")
    print(f"{'='*80}")

    for i, r in enumerate(valid[:top_n]):
        factor_name = r["factor"].split("(")[0].rstrip("_0123456789") if "(" not in r["factor"] else r["factor"].split("(")[0]
        lookback_raw = DEFAULT_LOOKBACKS.get(factor_name, [12])[0]

        sb = stratified_backtest(df, factor_name, lookback_raw)
        spread = sb["long_short_spread"]
        direction = "LONG low-factor" if spread > 0 else "SHORT high-factor"
        print(
            f"  {r['factor']:<30} spread={spread:+.4f} ({direction}) "
            f"| IC={r['ic_mean']:+.4f} ICIR={r['icir']:+.3f}"
        )
    print(f"{'='*80}\n")


if __name__ == "__main__":
    if "--stratify" in sys.argv:
        df = load_data()
        run_stratification(df)
    else:
        sys.exit(main())

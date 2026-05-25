"""factor-001: 延伸因子库 — 布林带、K线形态、成交量背离。

对 ETH/USDT 4h 数据进行三个新因子的 IC 分析、分层回测和 ADX 策略集成测试。

因子列表:
  1. bollinger_b       — 布林带 %b（均值回归信号）
  2. candlestick_*     — K线形态（十字星/锤子线/复合分数）
  3. volume_divergence — 成交量背离（ROC 法和相关系数法）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests import adx_adaptive_perp_eth_4h as mod
from strategies import momentum_factor as mf

DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"
OUT_DIR = PROJECT_ROOT / "loop" / "results" / "factor-001"
DATA_START = "2019-01-01"
DATA_END = "2026-05-21"

# 因子测试参数
TEST_FACTORS = {
    # Note: std_mult doesn't affect Pearson IC (linear-scale invariant)
    "bollinger_b": [(20, 2.0), (30, 2.0), (50, 2.0)],
    "candlestick_composite": [0],
    "candlestick_doji": [0.1, 0.15, 0.2],
    "candlestick_hammer": [0],
    "volume_divergence_roc": [12, 24, 48],
    "volume_divergence_corr": [14, 20, 40],
}

ADX_HI = 30
ADX_LO = 15


def _factor_base_name(label: str) -> str:
    """从 IC result label 反查 FACTOR_REGISTRY key。

    Example: 'volume_divergence_roc_48' → 'volume_divergence_roc'
             'bollinger_b(20, 2.0)' → 'bollinger_b'
    """
    return max(
        (n for n in mf.FACTOR_REGISTRY if label.startswith(n)),
        key=len,
        default=label.split("_")[0],
    )


def _factor_lookback(label: str, fname: str) -> int | tuple:
    """从 IC result label 提取 lookback 参数。"""
    suffix = label[len(fname) :]  # e.g. '_48' or '(20, 2.0)'
    if not suffix:
        return TEST_FACTORS.get(fname, [0])[0]
    if suffix.startswith("("):
        import ast

        try:
            return ast.literal_eval(suffix)
        except Exception:
            return TEST_FACTORS.get(fname, [0])[0]
    # Strip leading underscore and split
    nums_str = suffix.strip("_")
    nums = [x for x in nums_str.split("_") if x]
    try:
        vals = [float(x) if "." in x else int(x) for x in nums]
        return tuple(vals) if len(vals) > 1 else vals[0]
    except (ValueError, IndexError):
        return TEST_FACTORS.get(fname, [0])[0]


# ── IC 分析 ──────────────────────────────────────────────


def compute_ic_safe(
    df: pd.DataFrame, factor_name: str, lookback: int | tuple, fwd_periods: int = 1
) -> dict | None:
    """IC 分析与 momentum_factor.compute_ic 等效但含 error handling。"""
    try:
        fn = mf.FACTOR_REGISTRY[factor_name]
        args = lookback if isinstance(lookback, tuple) else (lookback,)
        factor = fn(df, *args)

        fwd_ret = df["close"].pct_change(fwd_periods).shift(-fwd_periods)
        aligned = pd.DataFrame({"factor": factor, "fwd": fwd_ret}).dropna()

        if len(aligned) < 100:
            logger.warning(f"  {factor_name}{args}: 数据不足 {len(aligned)}")
            return None

        ic = aligned["factor"].corr(aligned["fwd"])
        # 滚动 IC 用于 ICIR
        roll_ic = aligned["factor"].rolling(168).corr(aligned["fwd"]).dropna()
        if len(roll_ic) < 50:
            return None

        from scipy import stats

        t_stat, p_val = stats.ttest_1samp(roll_ic, 0.0)
        ic_mean = float(roll_ic.mean())
        ic_std = float(roll_ic.std())
        icir = ic_mean / ic_std if ic_std > 0 else 0.0
        cohens_d = abs(ic_mean) / ic_std if ic_std > 0 else 0.0
        hit_rate = float((roll_ic > 0).mean())

        return {
            "factor": mf.format_factor_label(factor_name, lookback),
            "ic_mean": round(ic_mean, 4),
            "icir": round(icir, 4),
            "hit_rate": round(hit_rate, 4),
            "p_value": round(float(p_val), 6),
            "cohens_d": round(cohens_d, 4),
            "n_obs": len(roll_ic),
        }
    except Exception as e:
        logger.warning(f"  {factor_name}{lookback}: 计算错误 — {e}")
        return None


# ── 分层回测 ─────────────────────────────────────────────


def stratified_longshort(
    df: pd.DataFrame, factor_name: str, lookback: int | tuple, n_groups: int = 5
) -> dict:
    """按因子值分层做多/做空，看是否单调。"""
    fn = mf.FACTOR_REGISTRY[factor_name]
    args = lookback if isinstance(lookback, tuple) else (lookback,)
    factor = fn(df, *args)

    fwd_ret = df["close"].pct_change(1).shift(-1)
    aligned = pd.DataFrame({"factor": factor, "fwd": fwd_ret}).dropna()

    try:
        aligned["group"] = pd.qcut(aligned["factor"], n_groups, labels=False, duplicates="drop")
    except ValueError:
        return {"error": "qcut 分箱失败（可能因子值过于集中）"}

    g = aligned.groupby("group")["fwd"].agg(["mean", "std", "count"])
    g["ann_ret"] = g["mean"] * 2190  # 4h → 年化 (365.25*6)
    g["ann_vol"] = g["std"] * np.sqrt(2190)
    g["sharpe"] = g["ann_ret"] / g["ann_vol"].replace(0, np.nan)

    label = mf.format_factor_label(factor_name, lookback)
    top = g.iloc[-1] if len(g) > 0 else None
    bot = g.iloc[0] if len(g) > 0 else None
    spread = float(top["ann_ret"]) - float(bot["ann_ret"]) if top is not None and bot is not None else 0

    return {
        "factor": label,
        "groups": g.to_dict(),
        "spread_pct": round(spread, 2),
        "monotonic": spread > 0,
    }


# ── ADX 策略集成测试 ──────────────────────────────────────


def adx_integration_test(
    df_sig: pd.DataFrame,
    factor_name: str,
    lookback: int | tuple,
    factor_col: str = "factor_z",
    filter_type: str = "confirm",  # "confirm" | "override" | "gate"
    threshold: float = 1.0,
) -> dict:
    """将因子信号集成到 ADX 策略，测试是否改善。

    filter_type:
      - confirm: 因子 Z-score 方向与 ADX 信号一致时才入场
      - override: 因子信号强烈时覆盖 ADX 规则
      - gate: 因子为 gate 时才允许入场
    """
    fn = mf.FACTOR_REGISTRY[factor_name]
    args = lookback if isinstance(lookback, tuple) else (lookback,)
    raw_factor = fn(df_sig, *args)

    # Z-score 标准化
    mean_f = raw_factor.mean()
    std_f = raw_factor.std()
    df_sig[factor_col] = (raw_factor - mean_f) / std_f if std_f > 0 else 0.0

    df_test = df_sig.copy()
    # 保存原始信号用于对比
    orig_long = df_test["long_sig"].copy()
    orig_short = df_test["short_sig"].copy()

    if filter_type == "confirm":
        # 因子方向必须与信号方向一致
        df_test["long_sig"] = orig_long & (df_test[factor_col] < -threshold)
        df_test["short_sig"] = orig_short & (df_test[factor_col] > threshold)
    elif filter_type == "override":
        # 因子极端时独立开仓
        df_test["long_sig"] = orig_long | (df_test[factor_col] < -threshold * 2)
        df_test["short_sig"] = orig_short | (df_test[factor_col] > threshold * 2)
    elif filter_type == "gate":
        # 因子非极端时才允许
        df_test["long_sig"] = orig_long & (df_test[factor_col].abs() < threshold)
        df_test["short_sig"] = orig_short & (df_test[factor_col].abs() < threshold)

    r = mod.run_backtest(df_test)
    return r


# ── 报告 ──────────────────────────────────────────────────


def ic_verdict(r: dict | None) -> str:
    if r is None:
        return "FAIL error"
    if r["p_value"] < 0.05 and abs(r["ic_mean"]) > 0.02 and r["icir"] > 0.3:
        return "PASS valid"
    if r["p_value"] < 0.10 and abs(r["ic_mean"]) > 0.01:
        return "WARN marginal"
    return "FAIL not-signif"


def classify_ic(r: dict | None) -> str:
    """返回简洁分类标签。"""
    if r is None:
        return "ERR"
    if r["p_value"] < 0.05:
        if abs(r["ic_mean"]) > 0.02 and r["icir"] > 0.3:
            return "PASS"
        if abs(r["ic_mean"]) > 0.01:
            return "WARN"
        return "WARN(L)"
    return "FAIL"


def print_ic_table(results: list[dict | None]) -> None:
    print(
        f"\n  {'Factor':<28} {'ICmean':>8} {'ICIR':>7} {'Hit%':>6} "
        f"{'p-val':>8} {'CohenD':>7} {'Verdict':>12}"
    )
    print(f"  {'─'*78}")
    for r in results:
        if r is None:
            continue
        cls = classify_ic(r)
        print(
            f"  {r['factor']:<28} {r['ic_mean']:>+8.4f} {r['icir']:>7.3f} "
            f"{r['hit_rate']:>6.1%} {r['p_value']:>8.4f} {r['cohens_d']:>7.3f} {cls:>12}"
        )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_lines: list[str] = []

    w = lambda *a, **kw: print(*a, **kw)
    rl = lambda line: report_lines.append(str(line))

    rl(f"# factor-001: Extension Factor Library — Bollinger, Candlestick, Volume Divergence\n")
    rl(f"- **Symbol**: ETH/USDT 4h")
    rl(f"- **Data**: {DATA_START} → {DATA_END}")
    rl(f"- **Task**: IC analysis + stratified backtest + ADX integration for 3 new factor families")
    rl(f"- **Params**: Fee 0.04%, Slippage 0.02%, Funding 0.00375%/bar, 10x lev\n")

    # ── 加载数据 ──
    w(f"\n{'='*90}")
    w(f"  Loading ETH/USDT 4h data...")
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    df = df.loc[DATA_START:DATA_END].copy()
    w(f"  Loaded {len(df)} bars: {df.index[0]} → {df.index[-1]}")
    rl(f"- **Data bars**: {len(df)}")

    # ── Phase 1: IC Analysis ──
    w(f"\n{'='*90}")
    w(f"  PHASE 1: IC Analysis — All Factors × All Parameters")
    w(f"{'='*90}\n")

    rl(f"\n## Phase 1: IC Analysis\n")
    rl(f"| Factor | ICmean | ICIR | Hit% | p-val | CohenD | Verdict |")
    rl(f"|---|---|---|---|---|---|---|")

    all_ic: list[dict | None] = []
    for fname, lookbacks in TEST_FACTORS.items():
        if fname not in mf.FACTOR_REGISTRY:
            w(f"  ⚠ {fname} not in FACTOR_REGISTRY, skipping")
            continue
        for lb in lookbacks:
            r = compute_ic_safe(df, fname, lb)
            all_ic.append(r)
            verdict = ic_verdict(r)
            w(f"  {r['factor'] if r else f'{fname}{lb}'}: {verdict.split()[0]}")

    print_ic_table(all_ic)

    for r in all_ic:
        if r is None:
            continue
        cls = classify_ic(r)
        rl(
            f"| {r['factor']} | {r['ic_mean']:+.4f} | {r['icir']:.3f} | "
            f"{r['hit_rate']:.1%} | {r['p_value']:.4f} | {r['cohens_d']:.3f} | {cls} |"
        )

    # 按 IC 强度排名
    valid_ic = [r for r in all_ic if r is not None]
    by_abs_ic = sorted(valid_ic, key=lambda x: abs(x["ic_mean"]), reverse=True)

    w(f"\n  Top 5 by |IC|:")
    for r in by_abs_ic[:5]:
        w(f"    {r['factor']:<28} IC={r['ic_mean']:+.4f}  ICIR={r['icir']:.3f}  p={r['p_value']:.4f}")

    rl(f"\n### IC Ranking (by |IC|)\n")
    rl(f"| Rank | Factor | ICmean | ICIR | p-val | Verdict |")
    rl(f"|---|---|---|---|---|---|")
    for rank, r in enumerate(by_abs_ic[:10], 1):
        cls = classify_ic(r)
        rl(f"| {rank} | {r['factor']} | {r['ic_mean']:+.4f} | {r['icir']:.3f} | {r['p_value']:.4f} | {cls} |")

    # ── Phase 2: Stratified Backtest ──
    w(f"\n{'='*90}")
    w(f"  PHASE 2: Stratified Backtest — Top IC Factors")
    w(f"{'='*90}\n")

    rl(f"\n## Phase 2: Stratified Backtest\n")
    rl(f"| Factor | L-S Spread | Monotonic | Q1 Ann% | Q5 Ann% |")
    rl(f"|---|---|---|---|---|")

    # Build factor_name → best IC result map for unique factor iteration
    best_per_factor: dict[str, dict] = {}
    for r in valid_ic:
        base = _factor_base_name(r["factor"])
        if base not in best_per_factor or abs(r["ic_mean"]) > abs(best_per_factor[base]["ic_mean"]):
            best_per_factor[base] = r

    # Sort unique factors by best |IC|
    sorted_factors = sorted(best_per_factor.items(), key=lambda x: abs(x[1]["ic_mean"]), reverse=True)

    for base_name, _ in sorted_factors[:5]:
        if base_name not in TEST_FACTORS:
            continue
        lb = TEST_FACTORS[base_name][0]
        sb = stratified_longshort(df, base_name, lb)
        if "error" not in sb:
            grp = sb["groups"]
            q_keys = sorted(grp.keys())
            q1_ann = grp[q_keys[0]].get("ann_ret", 0) if q_keys else 0
            q5_ann = grp[q_keys[-1]].get("ann_ret", 0) if q_keys else 0
            dir_str = "↗" if sb["monotonic"] else "↘"
            w(
                f"  {sb['factor']:<28}  spread={sb['spread_pct']:>+8.2f}%  {dir_str}  "
                f"Q1={q1_ann:.2%}  Q5={q5_ann:.2%}"
            )
            rl(
                f"| {sb['factor']} | {sb['spread_pct']:+.2f}% | {'Yes' if sb['monotonic'] else 'No'} | "
                f"{q1_ann:.2%} | {q5_ann:.2%} |"
            )

    # ── Phase 3: ADX Integration Test ──
    w(f"\n{'='*90}")
    w(f"  PHASE 3: ADX Strategy Integration — Filter Test")
    w(f"{'='*90}\n")

    rl(f"\n## Phase 3: ADX Strategy Integration\n")

    # 基准: ADX 基线 (ADX_TREND=30, ADX_RANGE=15)
    w(f"  Computing ADX baseline (ADX>{ADX_HI}/<{ADX_LO})...")
    mod.ADX_TREND = ADX_HI
    mod.ADX_RANGE = ADX_LO
    mod.FEE = 0.0004
    mod.SLIPPAGE = 0.0002
    mod.FUNDING_RATE = 0.0000375
    mod.MAX_LEVERAGE = 10.0
    mod.ATR_TRAIL_MULT = 2.5
    mod.MR_ATR_STOP_MULT = 3.5
    mod.RISK_PER_TRADE = 0.04
    mod.CB_MAX_LOSSES = 5
    mod.CB_COOLDOWN = 24

    df_sig = mod.compute_signals(df)
    if not mod._run_sanity(df_sig.copy()):
        logger.error("Sanity tests FAILED — aborting")
        return 1
    base_result = mod.run_backtest(df_sig)
    base_verdict = "PASS" if "error" not in base_result else "FAIL"
    w(f"  Baseline: Sharpe={base_result['sharpe_ratio']:.3f}  "
      f"Ret={base_result['total_return']:+.1f}%  "
      f"DD={base_result['max_drawdown']:.1f}%  "
      f"Trades={base_result['num_trades']}  "
      f"Win={base_result['win_rate']}%")

    rl(f"\n### Baseline (ADX>{ADX_HI}/<{ADX_LO}, ATR 2.5x)")
    rl(f"| Metric | Value |")
    rl(f"|---|---|")
    rl(f"| Sharpe | {base_result['sharpe_ratio']:.3f} |")
    rl(f"| Total Return | {base_result['total_return']:+.1f}% |")
    rl(f"| Max DD | {base_result['max_drawdown']:.1f}% |")
    rl(f"| Trades | {base_result['num_trades']} |")
    rl(f"| Win Rate | {base_result['win_rate']}% |")
    rl(f"| PF | {base_result.get('profit_factor', 0):.2f} |\n")

    # 对每个因子系列中 IC 最好的参数测试 ADX 集成
    integration_results: list[dict] = []

    w(f"\n  --- Integration: Confirm Mode (threshold=1.0) ---\n")
    rl(f"\n## Phase 3: ADX Strategy Integration — Confirm Mode\n")
    rl(f"| Factor | Sharpe | Ret% | DD% | Trades | Win% | PF | vs Baseline |")
    rl(f"|---|---|---|---|---|---|---|---|")

    for base_name, best_result in sorted_factors[:5]:
        if base_name not in TEST_FACTORS:
            continue
        lb = _factor_lookback(best_result["factor"], base_name)

        w(f"  Testing {base_name} (confirm mode, lb={lb}) ...")
        try:
            int_result = adx_integration_test(
                df_sig, base_name, lb, filter_type="confirm", threshold=1.0
            )
            if "error" in int_result:
                w(f"    SKIP: {int_result['error']}")
                continue

            sharpe_delta = int_result["sharpe_ratio"] - base_result["sharpe_ratio"]
            delta_str = f"+{sharpe_delta:.3f}" if sharpe_delta >= 0 else f"{sharpe_delta:.3f}"
            improvement = sharpe_delta > 0.01

            w(
                f"    Sharpe={int_result['sharpe_ratio']:.3f} ({delta_str})  "
                f"Ret={int_result['total_return']:+.1f}%  "
                f"DD={int_result['max_drawdown']:.1f}%  "
                f"Trades={int_result['num_trades']}  "
                f"Win={int_result['win_rate']}%"
            )
            integration_results.append({
                "factor": best_result["factor"],
                "sharpe": int_result["sharpe_ratio"],
                "ret": int_result["total_return"],
                "dd": int_result["max_drawdown"],
                "trades": int_result["num_trades"],
                "win_rate": int_result["win_rate"],
                "pf": int_result.get("profit_factor", 0),
                "sharpe_delta": sharpe_delta,
                "improved": improvement,
            })
            rl(
                f"| {best_result['factor']} | {int_result['sharpe_ratio']:.3f} | {int_result['total_return']:+.1f}% | "
                f"{int_result['max_drawdown']:.1f}% | {int_result['num_trades']} | "
                f"{int_result['win_rate']}% | {int_result.get('profit_factor', 0):.2f} | "
                f"{delta_str} |"
            )
        except Exception as e:
            w(f"    ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue

    # ── Phase 4: Summary ──
    w(f"\n{'='*90}")
    w(f"  PHASE 4: Summary & Recommendations")
    w(f"{'='*90}\n")

    # 统计
    passed_ic = sum(1 for r in valid_ic if classify_ic(r) == "PASS")
    warn_ic = sum(1 for r in valid_ic if classify_ic(r) == "WARN")
    failed_ic = sum(1 for r in valid_ic if classify_ic(r) == "FAIL")
    improved = sum(1 for r in integration_results if r.get("improved"))

    rl(f"\n## Phase 4: Summary\n")
    rl(f"- **IC Analysis**: {len(valid_ic)} combos | PASS: {passed_ic} | WARN: {warn_ic} | FAIL: {failed_ic}")
    rl(f"- **ADX Integration**: {improved}/{len(integration_results)} factors improved Sharpe over baseline")

    summary_lines = []

    for r in by_abs_ic[:3]:
        summary_lines.append(f"\n- **{r['factor']}**: IC={r['ic_mean']:+.4f}, ICIR={r['icir']:.3f}, p={r['p_value']:.4f}")

    w(f"  IC Analysis: {len(valid_ic)} combos | PASS: {passed_ic} | WARN: {warn_ic} | FAIL: {failed_ic}")
    w(f"  ADX Integration: {improved}/{len(integration_results)} factors improved Sharpe")
    w(f"\n  Top IC Factors:")
    for r in by_abs_ic[:5]:
        w(f"    {r['factor']:<28}  IC={r['ic_mean']:+.4f}  ICIR={r['icir']:.3f}  p={r['p_value']:.4f}  {classify_ic(r)}")

    w(f"\n  Integration improvements:")
    for r in integration_results:
        if r["improved"]:
            w(f"    [+] {r['factor']}: Sharpe +{r['sharpe_delta']:.3f}")
        else:
            w(f"    [-] {r['factor']}: Sharpe {r['sharpe_delta']:.3f}")

    rl("".join(summary_lines))
    rl(f"\n## Verdict\n")

    if passed_ic >= 2 or improved >= 1:
        rl(f"**PASS** — Valid factors identified with predictive IC. "
           f"{improved}/{len(integration_results)} factors improved ADX strategy when used as confirmation filter.\n")
    elif warn_ic >= 3:
        rl(f"**WARN** — Some factors show marginal predictive power but insufficient for standalone use. "
           f"May be useful as secondary signals in multi-factor ensemble.\n")
    else:
        rl(f"**FAIL** — No factors demonstrate meaningful predictive power on this asset/timeframe.\n")

    # ── Write report ──
    report = "\n".join(report_lines)
    report_path = OUT_DIR / "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"Report written: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Walk-Forward 验证：永续合约 + Binance 真实费率 + 复利计算。

每窗口: 8 月样本内优化 → 4 月样本外验证 → 复利累积 OOS 权益曲线
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C  # noqa: E402

# 永续策略 (ADX>30/<15 baseline)
from backtests.adx_adaptive_perp_eth_4h import (  # noqa: E402
    MAX_LEVERAGE,
    PROJECT_ROOT,
    calc_contracts,
    compute_signals,
    load_data,
    run_backtest,
)
import backtests.adx_adaptive_perp_eth_4h as strat_mod  # noqa: E402

# ── Walk-Forward 参数 ────────────────────────────────────────────────
WINDOW_MONTHS = 8
STEP_MONTHS = 4
MIN_TRADES = 5

# 参数网格 — 只扫 ATR（ADX 阈值已固定为基线值 30/15）
# 网格加细，找 ATR 随时间的最优漂移
ATR_GRID = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0]

# ── 费用参数（每次 run 前重置）────────────────────────────────────────
def reset_costs() -> None:
    strat_mod.FEE = C.FEE_TAKER
    strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
    strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
    strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def run_params(df: pd.DataFrame, atr_m: float) -> dict | None:
    """跑一组参数，返回摘要。每次入口重算信号 + 重置费用。"""
    reset_costs()
    df_copy = df.copy()
    df_copy = compute_signals(df_copy)
    strat_mod.ATR_TRAIL_MULT = atr_m
    strat_mod.MR_ATR_STOP_MULT = atr_m + 1.0
    r = run_backtest(df_copy)
    if "error" in r or r["num_trades"] < MIN_TRADES:
        return None
    return r


# ── 加载数据 ──────────────────────────────────────────────────────────
DATA_PATH = ROOT / "data" / "eth_usdt_4h.csv"
df_full = load_data(DATA_PATH)
df_full = compute_signals(df_full)
reset_costs()

logger.info(f"Data: {df_full.index[0]} → {df_full.index[-1]} ({len(df_full)} bars)")

# ── 生成窗口 ──────────────────────────────────────────────────────────
start_dates = pd.date_range(
    start=df_full.index.min(),
    end=df_full.index.max() - pd.DateOffset(months=WINDOW_MONTHS + STEP_MONTHS),
    freq=pd.DateOffset(months=STEP_MONTHS),
)

print(f"\n{'=' * 90}")
print("Walk-Forward Validation (Perpetual 10x · Binance 真实费率 · 复利累积)")
print(f"  ATR grid: {ATR_GRID}")
print(f"  ADX: >{strat_mod.ADX_TREND} / <{strat_mod.ADX_RANGE} (基线已固定)")
print(f"  Fees: taker {C.FEE_TAKER*100:.2f}% · slippage {C.SLIPPAGE_ETH*100:.2f}% · funding {C.FUNDING_RATE_4H_ETH*100:.4f}%/4h")
print(f"  Leverage: {C.MAX_LEVERAGE}x · Risk: {C.RISK_PER_TRADE*100:.0f}%/trade")
print(f"{'=' * 90}")
print()

windows: list[dict] = []
oos_equity: list[float] = [1.0]  # 复利累积 OOS 权益曲线
prev_eq = 1.0

for i, ws in enumerate(start_dates[:-1]):
    is_start = ws
    is_end = ws + pd.DateOffset(months=WINDOW_MONTHS)
    oos_end = is_end + pd.DateOffset(months=STEP_MONTHS)

    if oos_end > df_full.index.max():
        break

    df_is = df_full[(df_full.index >= is_start) & (df_full.index < is_end)].copy()
    df_oos = df_full[(df_full.index >= is_end) & (df_full.index < oos_end)].copy()

    if len(df_is) < 200 or len(df_oos) < 100:
        continue

    # ── 样本内优化 (网格搜索 ATR ─ 信号已在 run_params 内重算) ──
    best_params = None
    best_sharpe = -999
    for atr_m in ATR_GRID:
        r = run_params(df_is, atr_m)
        if r and r["sharpe_ratio"] > best_sharpe:
            best_sharpe = r["sharpe_ratio"]
            best_params = atr_m

    if best_params is None:
        continue

    # ── 样本外测试 ──
    r_oos = run_params(df_oos, best_params)
    if r_oos is None:
        continue

    # 累积复利 OOS 收益
    oos_ret = r_oos["total_return"] / 100
    prev_eq *= (1 + oos_ret)
    oos_equity.append(prev_eq)

    windows.append({
        "is_period": f"{is_start.date()}→{is_end.date()}",
        "oos_period": f"{is_end.date()}→{oos_end.date()}",
        "best_atr": best_params,
        "is_sharpe": best_sharpe,
        "oos_return": r_oos["total_return"],
        "oos_sharpe": r_oos["sharpe_ratio"],
        "oos_dd": r_oos["max_drawdown"],
        "oos_trades": r_oos["num_trades"],
        "oos_pf": r_oos["profit_factor"],
        "oos_win_rate": r_oos["win_rate"],
        "oos_liqs": r_oos["liquidations"],
    })

    logger.info(
        f"Window {len(windows)}: IS={is_start.date()}+{WINDOW_MONTHS}m "
        f"OOS Sharpe={r_oos['sharpe_ratio']:.3f} "
        f"ATR={best_params}x "
        f"Cum Eq={prev_eq:.3f}"
    )

# ── 汇总 ──
if not windows:
    logger.error("No valid windows")
    sys.exit(1)

total_windows = len(windows)
oos_rets = [w["oos_return"] for w in windows]
oos_sharpes = [w["oos_sharpe"] for w in windows]
oos_dds = [w["oos_dd"] for w in windows]
win_count = sum(1 for r in oos_rets if r > 0)

# 复利累积 OOS 总收益
cum_ret_pct = (oos_equity[-1] - 1) * 100
n_years = (windows[-1]["oos_period"].split("→")[1] if "→" in windows[-1]["oos_period"] else df_full.index[-1].date()).split()
# compute years from data range
first_oos_start = pd.Timestamp(windows[0]["oos_period"].split("→")[0])
last_oos_end = pd.Timestamp(windows[-1]["oos_period"].split("→")[1])
total_years = (last_oos_end - first_oos_start).days / 365.25
ann_ret = (oos_equity[-1] ** (1 / total_years) - 1) * 100 if total_years > 0 else 0

# OOS 权益曲线的夏普
oos_eq_series = pd.Series(oos_equity)
daily_rets = oos_eq_series.pct_change().dropna()
oos_ann_vol = float(daily_rets.std() * np.sqrt(365.25)) if len(daily_rets) > 1 else 0
oos_sharpe_cum = ann_ret / 100 / oos_ann_vol if oos_ann_vol > 0 else 0

# OOS 回撤
oos_peak = pd.Series(oos_equity).expanding().max()
oos_dd_series = (oos_peak - pd.Series(oos_equity)) / oos_peak
oos_max_dd = float(oos_dd_series.max()) * 100

print("\n" + "=" * 90)
print("  Walk-Forward Results")
print("=" * 90)

# 表头
print(f"\n  {'Window':<6} {'IS Period':<22} {'OOS Period':<22} {'ATR':<5} "
      f"{'IS Sh':>7} {'OOS Ret':>8} {'OOS Sh':>7} {'OOS DD':>7} {'PF':>6} {'Trades':>7} {'Liq':>4}")
print("  " + "-" * 104)

for i, w in enumerate(windows):
    print(f"  {i:<6} {w['is_period']:<22} {w['oos_period']:<22} {w['best_atr']:<5.2f} "
          f"{w['is_sharpe']:>7.3f} {w['oos_return']:>+7.1f}% {w['oos_sharpe']:>7.3f} "
          f"{w['oos_dd']:>6.1f}% {w['oos_pf']:>6.2f} {w['oos_trades']:>7} {w['oos_liqs']:>4}")

print()
print(f"  Windows OOS positive:        {win_count}/{total_windows} ({win_count/total_windows*100:.0f}%)")
print(f"  OOS return range:            {min(oos_rets):+.1f}% ~ {max(oos_rets):+.1f}%")
print(f"  OOS Sharpe range:            {min(oos_sharpes):+.3f} ~ {max(oos_sharpes):+.3f}")
print(f"  Mean OOS return:             {np.mean(oos_rets):+.1f}%")
print(f"  Median OOS Sharpe:           {np.median(oos_sharpes):+.3f}")
print()
print(f"  Cumulative OOS equity:       {oos_equity[-1]:.4f}x")
print(f"  Cumulative OOS return:       {cum_ret_pct:+.2f}%")
print(f"  Annualized (OOS cumulative): {ann_ret:+.2f}%")
print(f"  Max OOS drawdown:            {oos_max_dd:.2f}%")
print(f"  OOS cumulative Sharpe:       {oos_sharpe_cum:.3f}")
print(f"  Time span:                   {first_oos_start.date()} → {last_oos_end.date()} ({total_years:.1f} yrs)")
print()

# ── 判断 ──
pos_rate = win_count / total_windows
mean_oos = np.mean(oos_rets)
print(f"  Decision criteria:")
print(f"    Positive windows: {pos_rate*100:.0f}% (≥ 60% → PASS)")
print(f"    Positive cumulative OOS: {'YES' if cum_ret_pct > 0 else 'NO'}")
print(f"    Zero liquidations: {'YES' if sum(w['oos_liqs'] for w in windows) == 0 else 'NO'}")
print()

if pos_rate >= 0.6 and cum_ret_pct > 0:
    verdict = "PASS"
    msg = "Walk-Forward confirmed — strategy generalizes with current Binance costs and compounding"
elif pos_rate >= 0.5 and cum_ret_pct > 0:
    verdict = "WARN"
    msg = "Marginal — edge exists but inconsistent across windows"
elif cum_ret_pct > 0:
    verdict = "WARN"
    msg = "Cumulative positive but low win rate — check regime dependency"
else:
    verdict = "FAIL"
    msg = "Cumulative OOS negative — strategy fails under Walk-Forward with real costs"

print(f"  === {verdict}: {msg} ===")
print()

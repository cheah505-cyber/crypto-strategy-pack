"""Walk-Forward 验证：滚动窗口优化+验证，模拟实盘持续调参。

每窗口: 6 月样本内优化 → 3 月样本外验证 → 拼接成连续权益曲线
"""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from backtests.adx_adaptive import load_data, compute_signals
import backtests.adx_adaptive as mod

WINDOW_MONTHS = 8
STEP_MONTHS = 4
MIN_TRADES = 3

# 参数网格
ATR_GRID = [1.5, 2.0, 2.5, 3.0]
ADX_GRID = [(30, 20), (25, 20), (30, 15), (25, 15), (22, 18)]


def run_params(df, atr_m, adx_hi, adx_lo):
    """跑一组参数，返回摘要指标。"""
    mod.ATR_TRAIL_MULT = atr_m
    mod.MR_ATR_STOP_MULT = atr_m + 1.0
    mod.ADX_TREND = adx_hi
    mod.ADX_RANGE = adx_lo
    r = mod.run_backtest(df.copy())
    if "error" in r or r["num_trades"] < MIN_TRADES:
        return None
    return r


# ── 加载数据 ──
df_full = load_data()
df_full = compute_signals(df_full)

# 生成窗口
start_dates = pd.date_range(
    start=df_full.index.min(),
    end=df_full.index.max() - pd.DateOffset(months=WINDOW_MONTHS + STEP_MONTHS),
    freq=pd.DateOffset(months=STEP_MONTHS),
)

print(f"{'='*80}")
print("Walk-Forward Validation: Rolling 6-month IS + 3-month OOS")
print(f"{'='*80}")
print(f"Windows: {len(start_dates)}")
print(f"Param grid: ATR={ATR_GRID}, ADX={ADX_GRID}")
print()

windows = []

for i, window_start in enumerate(start_dates[:-1]):  # last window may not have OOS
    is_start = window_start
    is_end = window_start + pd.DateOffset(months=WINDOW_MONTHS)
    oos_end = is_end + pd.DateOffset(months=STEP_MONTHS)

    if oos_end > df_full.index.max():
        break

    df_is = df_full[(df_full.index >= is_start) & (df_full.index < is_end)]
    df_oos = df_full[(df_full.index >= is_end) & (df_full.index < oos_end)]

    if len(df_is) < 100 or len(df_oos) < 50:
        continue

    # ── 样本内优化 ──
    best_params = None
    best_sharpe = -999
    for atr_m in ATR_GRID:
        for adx_hi, adx_lo in ADX_GRID:
            if adx_lo >= adx_hi:
                continue
            r = run_params(df_is, atr_m, adx_hi, adx_lo)
            if r and r["sharpe_ratio"] > best_sharpe:
                best_sharpe = r["sharpe_ratio"]
                best_params = (atr_m, adx_hi, adx_lo)

    if best_params is None:
        continue

    # ── 样本外测试 ──
    atr_m, adx_hi, adx_lo = best_params
    r_oos = run_params(df_oos, atr_m, adx_hi, adx_lo)
    if r_oos is None:
        continue

    windows.append({
        "is_period": f"{str(is_start)[:10]}→{str(is_end)[:10]}",
        "oos_period": f"{str(is_end)[:10]}→{str(oos_end)[:10]}",
        "best_params": f"ATR={atr_m} ADX>{adx_hi}/<{adx_lo}",
        "is_sharpe": best_sharpe,
        "oos_return": r_oos["total_return"],
        "oos_sharpe": r_oos["sharpe_ratio"],
        "oos_dd": r_oos["max_drawdown"],
        "oos_trades": r_oos["num_trades"],
        "oos_pf": r_oos["profit_factor"],
    })

# ── 汇总 ──
if not windows:
    print("ERROR: No valid windows")
    sys.exit(1)

print(f"{'IS Period':<22} {'OOS Period':<22} {'Best Params':<22} {'IS Sh':>7} {'OOS Ret':>8} {'OOS Sh':>7} {'OOS DD':>7} {'Trades':>7}")
print("-" * 109)
for w in windows:
    print(f"{w['is_period']:<22} {w['oos_period']:<22} {w['best_params']:<22} "
          f"{w['is_sharpe']:>7.3f} {w['oos_return']:>+7.1f}% {w['oos_sharpe']:>7.3f} "
          f"{w['oos_dd']:>6.1f}% {w['oos_trades']:>7}")

print()
oos_rets = [w["oos_return"] for w in windows]
oos_sharpes = [w["oos_sharpe"] for w in windows]
win_count = sum(1 for r in oos_rets if r > 0)
total_windows = len(windows)

print(f"Windows OOS positive: {win_count}/{total_windows} ({win_count/total_windows*100:.0f}%)")
print(f"OOS return range: {min(oos_rets):+.1f}% ~ {max(oos_rets):+.1f}%")
print(f"OOS sharpe range: {min(oos_sharpes):+.3f} ~ {max(oos_sharpes):+.3f}")
print(f"Mean OOS return: {np.mean(oos_rets):+.1f}%")
print(f"Mean OOS sharpe: {np.mean(oos_sharpes):+.3f}")

# 累积 OOS 收益
cum_ret = 1.0
for w in windows:
    cum_ret *= (1 + w["oos_return"] / 100)
cum_ret = (cum_ret - 1) * 100

print()
print(f"Cumulative OOS return: {cum_ret:+.1f}%")
print(f"Frame count: {total_windows}")

# 判断
pos_rate = win_count / total_windows if total_windows > 0 else 0
mean_oos = np.mean(oos_rets)
if pos_rate >= 0.6 and mean_oos > 0:
    print("=== PASS: Walk-Forward confirmed — strategy generalizes across time ===")
elif pos_rate >= 0.5 and mean_oos > 0:
    print("=== WARN: Marginal — edge exists but inconsistent across windows ===")
else:
    print("=== FAIL: Walk-Forward rejected — strategy is overfit to specific period ===")

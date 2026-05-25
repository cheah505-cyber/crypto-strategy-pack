"""波动因子三方向测试：扩张确认 / 压缩突破 / ATR 比率过滤。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals, run_backtest, print_report
import backtests.adx_adaptive_perp_eth_4h as strat_mod

INITIAL = 10_000

strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 2.5
strat_mod.MR_ATR_STOP_MULT = 3.5
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

# 全局基线
df_full = load_data()
if df_full.index.tz is not None: df_full.index = df_full.index.tz_localize(None)
df_full = compute_signals(df_full)

baseline = run_backtest(df_full)
base_final = INITIAL * (1 + baseline["total_return"] / 100)

print("=" * 70)
print("  波动因子测试 — Full Cycle 2019-2026")
print("=" * 70)
print(f"  4h 基线: ${base_final:,.0f}  Ret {baseline['total_return']:+.1f}%  "
      f"Sharpe {baseline['sharpe_ratio']:.3f}  DD {baseline['max_drawdown']:.1f}%  "
      f"Trades {baseline['num_trades']}")
print()

# ── 计算波动因子列 ──────────────────────────────────────────────
df = df_full.copy()

# ATR 比率: 当前ATR / 20期均值ATR
df['atr_20'] = df['atr'].rolling(20).mean()
df['atr_ratio'] = df['atr'] / df['atr_20'].replace(0, np.nan)

# ATR 加速度: ATR比率的斜率（动量）
df['atr_momentum'] = df['atr_ratio'].diff(5)

# 布林带带宽: (上轨 - 下轨) / 中轨
df['bb_mid'] = df['close'].rolling(20).mean()
df['bb_std'] = df['close'].rolling(20).std()
df['bb_width'] = 2 * df['bb_std'] * 2 / df['bb_mid'] * 100  # 百分比带宽
# 带宽百分位: 当前带宽在60期窗口中的位置
df['bb_width_pct'] = df['bb_width'].rolling(60).apply(
    lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() > x.min() else 0.5
)

print(f"  ATR ratio range: {df['atr_ratio'].min():.2f} ~ {df['atr_ratio'].max():.2f} (mean {df['atr_ratio'].mean():.2f})")
print(f"  BB width range: {df['bb_width'].min():.1f}% ~ {df['bb_width'].max():.1f}%")
print()

# ── 测试1: ATR 比率过滤 ────────────────────────────────────────
print("-" * 70)
print("  测试1: ATR 比率过滤 (atr_ratio > threshold 才交易)")
print("-" * 70)

for thr in [1.0, 1.2, 1.3, 1.5]:
    dft = df.copy()
    # 过滤：atr_ratio 低于阈值时取消所有信号
    mask_low = dft['atr_ratio'].fillna(0) < thr
    dft.loc[mask_low, 'long_sig'] = False
    dft.loc[mask_low, 'short_sig'] = False
    r = run_backtest(dft)
    if "error" in r:
        print(f"  thr={thr:.1f}: ERROR")
        continue
    final = INITIAL * (1 + r["total_return"] / 100)
    kept = int((~mask_low).sum())
    print(f"  thr={thr:.1f}  Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Kept {kept} bars")

print()

# ── 测试2: ATR 扩张确认 ────────────────────────────────────────
print("-" * 70)
print("  测试2: ATR 扩张确认 (atr_momentum > threshold 才交易)")
print("-" * 70)

for thr in [0, 0.02, 0.05]:
    dft = df.copy()
    mask = dft['atr_momentum'].fillna(0) < thr
    dft.loc[mask, 'long_sig'] = False
    dft.loc[mask, 'short_sig'] = False
    r = run_backtest(dft)
    if "error" in r:
        print(f"  mom>{thr}: ERROR")
        continue
    final = INITIAL * (1 + r["total_return"] / 100)
    kept = int((~mask).sum())
    print(f"  mom>{thr:<4} Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Kept {kept} bars")

print()

# ── 测试3: 布林带压缩突破 (独立策略) ────────────────────────────
print("-" * 70)
print("  测试3: 布林带压缩突破 (BB width pct < threshold → 突破开仓)")
print("-" * 70)

for thr in [0.1, 0.2, 0.3]:
    dft = df.copy()
    # 带宽极度收窄 → 准备突破
    squeezed = dft['bb_width_pct'].fillna(0.5) < thr
    # 在压缩状态下，close 突破 bb_mid ± 1*bb_std 时开仓
    dft['bb_long_sig'] = squeezed & (dft['close'] > dft['bb_mid'] + dft['bb_std'])
    dft['bb_short_sig'] = squeezed & (dft['close'] < dft['bb_mid'] - dft['bb_std'])

    # 替换主信号
    dft['long_sig'] = dft['bb_long_sig']
    dft['short_sig'] = dft['bb_short_sig']

    r = run_backtest(dft)
    if "error" in r:
        print(f"  bb<{thr:.1f}: ERROR")
        continue
    final = INITIAL * (1 + r["total_return"] / 100)
    sigs = int(dft['long_sig'].sum() + dft['short_sig'].sum())
    print(f"  bb<{thr:.1f}  Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Signals {sigs}")

print()

# ── 测试4: 最佳组合 ────────────────────────────────────────────
print("-" * 70)
print("  测试4: ATR ratio ≥ 1.2 + atr_momentum > 0 (组合过滤)")
print("-" * 70)

dft = df.copy()
mask = (dft['atr_ratio'].fillna(0) < 1.2) | (dft['atr_momentum'].fillna(0) <= 0)
dft.loc[mask, 'long_sig'] = False
dft.loc[mask, 'short_sig'] = False
r = run_backtest(dft)
final = INITIAL * (1 + r["total_return"] / 100)
print(f"  Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
      f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
      f"Trades {r['num_trades']}")

print()
print("=" * 70)
print("  对比 4h 基线")
print("=" * 70)
print(f"  ${base_final:,.0f}  Ret {baseline['total_return']:+.1f}%  "
      f"Sharpe {baseline['sharpe_ratio']:.3f}  DD {baseline['max_drawdown']:.1f}%")
print()

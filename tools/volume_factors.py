"""成交量因子测试 — 量价配合 / 缩量 / 放量确认。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals, run_backtest
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

df_full = load_data()
if df_full.index.tz is not None: df_full.index = df_full.index.tz_localize(None)
df_full = compute_signals(df_full)

# 计算成交量因子
df_full["volume_ma20"] = df_full["volume"].rolling(20).mean()
df_full["volume_ma50"] = df_full["volume"].rolling(50).mean()
df_full["vol_ratio"] = df_full["volume"] / df_full["volume_ma20"].replace(0, np.nan)
df_full["vol_ma_ratio"] = df_full["volume_ma20"] / df_full["volume_ma50"].replace(0, np.nan)

# OBV (On-Balance Volume)
df_full["obv"] = (np.sign(df_full["close"].diff()) * df_full["volume"]).fillna(0).cumsum()
df_full["obv_ma"] = df_full["obv"].rolling(20).mean()
df_full["obv_ratio"] = df_full["obv"] / df_full["obv_ma"].replace(0, np.nan)

# 量价相关性 (rolling 20期)
def rolling_corr(x, y, w=20):
    return x.rolling(w).corr(y)

df_full["vol_price_corr"] = rolling_corr(df_full["volume"], df_full["close"], 20)

# 放量突破: 价格创新高 + 量放大
df_full["vol_spike"] = df_full["vol_ratio"] > 1.5
df_full["vol_ma_expanding"] = df_full["vol_ma_ratio"] > 1.0

baseline = run_backtest(df_full)
base_final = INITIAL * (1 + baseline["total_return"] / 100)

print("=" * 70)
print("  成交量因子测试 — Full Cycle 2019-2026")
print("=" * 70)
print(f"  基线: ${base_final:,.0f}  Ret {baseline['total_return']:+.1f}%  "
      f"Sharpe {baseline['sharpe_ratio']:.3f}  DD {baseline['max_drawdown']:.1f}%  "
      f"Trades {baseline['num_trades']}")
print()

# ── 测试1: 放量确认 (vol_ratio > threshold 才交易) ──
print("-" * 70)
print("  测试1: 放量确认 — volume > 均值×倍数 才交易")
print("-" * 70)

for thr in [0.8, 1.0, 1.2, 1.5]:
    dft = df_full.copy()
    mask = dft["vol_ratio"].fillna(0) < thr
    dft.loc[mask, "long_sig"] = False
    dft.loc[mask, "short_sig"] = False
    r = run_backtest(dft)
    if "error" in r: continue
    final = INITIAL * (1 + r["total_return"] / 100)
    kept = int((~mask).sum())
    print(f"  vol>{thr:<4} Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Kept {kept}")

print()

# ── 测试2: 量比趋势确认 (vol_ma 扩张才交易) ──
print("-" * 70)
print("  测试2: 量比趋势 — 20日均量 > 50日均量")
print("-" * 70)

dft = df_full.copy()
mask = ~dft["vol_ma_expanding"].fillna(False)
dft.loc[mask, "long_sig"] = False
dft.loc[mask, "short_sig"] = False
r = run_backtest(dft)
final = INITIAL * (1 + r["total_return"] / 100)
kept = int(dft["vol_ma_expanding"].sum())
print(f"  vol_ma>1  Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
      f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
      f"Trades {r['num_trades']}  Kept {kept}")

print()

# ── 测试3: OBV 趋势确认 ──
print("-" * 70)
print("  测试3: OBV 趋势 — OBV > 20日均值才交易")
print("-" * 70)

dft = df_full.copy()
mask = dft["obv_ratio"].fillna(0) < 1.0
dft.loc[mask, "long_sig"] = False
dft.loc[mask, "short_sig"] = False
r = run_backtest(dft)
final = INITIAL * (1 + r["total_return"] / 100)
kept = int((~mask).sum())
print(f"  obv>1    Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
      f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
      f"Trades {r['num_trades']}  Kept {kept}")

# OBV 多头/空头分开
for side_label, sig_col in [("做多", "long_sig"), ("做空", "short_sig")]:
    dft = df_full.copy()
    if "long" in sig_col:
        mask = dft["obv_ratio"].fillna(0) < 1.0
    else:
        mask = dft["obv_ratio"].fillna(0) > 1.0
    dft.loc[mask, sig_col] = False
    r = run_backtest(dft)
    if "error" not in r:
        final = INITIAL * (1 + r["total_return"] / 100)
        print(f"  OBV {side_label:<4} Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
              f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
              f"Trades {r['num_trades']}")

print()

# ── 测试4: 量价背离 — 价格方向与成交量方向不一致时不做 ──
print("-" * 70)
print("  测试4: 量价一致 — vol_price_corr > 0 才交易")
print("-" * 70)

for thr in [-0.3, 0, 0.3]:
    dft = df_full.copy()
    mask = dft["vol_price_corr"].fillna(0) < thr
    dft.loc[mask, "long_sig"] = False
    dft.loc[mask, "short_sig"] = False
    r = run_backtest(dft)
    if "error" in r: continue
    final = INITIAL * (1 + r["total_return"] / 100)
    kept = int((~mask).sum())
    print(f"  corr>{thr:<4} Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Kept {kept}")

print()

# ── 测试5: 最佳组合 ──
print("-" * 70)
print("  测试5: 放量(>1.0) + 量比趋势(>1.0)")
print("-" * 70)

dft = df_full.copy()
mask = (dft["vol_ratio"].fillna(0) < 1.0) | (~dft["vol_ma_expanding"].fillna(False))
dft.loc[mask, "long_sig"] = False
dft.loc[mask, "short_sig"] = False
r = run_backtest(dft)
final = INITIAL * (1 + r["total_return"] / 100)
print(f"  Final ${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
      f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
      f"Trades {r['num_trades']}")

print()
print("=" * 70)
print("  对照: 4h 基线")
print("=" * 70)
print(f"  ${base_final:,.0f}  Ret {baseline['total_return']:+.1f}%  "
      f"Sharpe {baseline['sharpe_ratio']:.3f}  DD {baseline['max_drawdown']:.1f}%")
print()

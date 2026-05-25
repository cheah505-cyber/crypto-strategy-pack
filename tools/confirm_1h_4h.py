"""1h 做基线 + 4h 过滤。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
import backtests.adx_adaptive_perp_eth_4h as strat_mod

INITIAL_CAPITAL = 10_000
START_DATE = "2025-06-01"
END_DATE = "2026-05-25"

# 1h 参数
strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 4.2
strat_mod.MR_ATR_STOP_MULT = 5.2
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def calc_4h_adx_rsi(df_4h: pd.DataFrame) -> pd.DataFrame:
    """计算 4h ADX/RSI。"""
    df = df_4h.copy()
    c = df["close"]
    delta = c.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    df["rsi_4h"] = 100 - 100/(1 + avg_gain/avg_loss.replace(0, np.nan))
    h, l = df["high"], df["low"]
    tr1, tr2, tr3 = h-l, (h-c.shift()).abs(), (l-c.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, min_periods=14).mean()
    up, down = h-h.shift(), l.shift()-l
    pdm = pd.Series(np.where((up>down)&(up>0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((down>up)&(down>0), down, 0.0), index=df.index)
    pdi = 100*(pdm.ewm(alpha=1/14, min_periods=14).mean()/atr.replace(0,np.nan))
    ndi = 100*(ndm.ewm(alpha=1/14, min_periods=14).mean()/atr.replace(0,np.nan))
    dx = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0, np.nan)
    df["adx_4h"] = dx.ewm(alpha=1/14, min_periods=14).mean()
    df["is_trend_4h"] = (df["adx_4h"] > 30).astype(int)
    return df[["rsi_4h", "adx_4h", "is_trend_4h"]]


def run_1h_with_4h_filter(mode: str = "regime") -> dict:
    """1h 策略 + 4h 确认。mode: regime / rsi / either / both"""
    # 加载
    df_1h = strat_mod.load_data(ROOT / "data" / "eth_usdt_1h.csv")
    df_4h = strat_mod.load_data(ROOT / "data" / "eth_usdt_4h.csv")
    for d in [df_1h, df_4h]:
        if d.index.tz is not None:
            d.index = d.index.tz_localize(None)

    # 计算信号
    df_1h = df_1h[(df_1h.index >= START_DATE) & (df_1h.index < END_DATE)].copy()
    df_1h = strat_mod.compute_signals(df_1h)

    # 4h 指标 → 按 1h 频率前向填充
    df_4h_filter = calc_4h_adx_rsi(df_4h)
    df_4h_1h = df_4h_filter.reindex(df_1h.index, method="ffill")
    df_1h = pd.concat([df_1h, df_4h_1h], axis=1)

    sig_before = int(df_1h["long_sig"].sum() + df_1h["short_sig"].sum())

    for i in range(len(df_1h)):
        row = df_1h.iloc[i]
        rsi4 = row.get("rsi_4h", np.nan)
        trend4 = row.get("is_trend_4h", 0)

        if pd.isna(rsi4):
            df_1h.iloc[i, df_1h.columns.get_loc("long_sig")] = False
            df_1h.iloc[i, df_1h.columns.get_loc("short_sig")] = False
            continue

        if bool(row["long_sig"]):
            keep = False
            if mode == "regime" and bool(trend4):
                keep = True  # 4h 也是趋势模式 → 确认做多
            elif mode == "rsi" and rsi4 < 50:
                keep = True  # 4h 不超买
            elif mode == "either" and (bool(trend4) or rsi4 < 50):
                keep = True
            elif mode == "both" and bool(trend4) and rsi4 < 50:
                keep = True
            if not keep:
                df_1h.iloc[i, df_1h.columns.get_loc("long_sig")] = False

        if bool(row["short_sig"]):
            keep = False
            if mode == "regime" and bool(trend4):
                keep = True  # 4h 趋势 → 做空确认
            elif mode == "rsi" and rsi4 > 50:
                keep = True  # 4h 不超卖
            elif mode == "either" and (bool(trend4) or rsi4 > 50):
                keep = True
            elif mode == "both" and bool(trend4) and rsi4 > 50:
                keep = True
            if not keep:
                df_1h.iloc[i, df_1h.columns.get_loc("short_sig")] = False

    sig_after = int(df_1h["long_sig"].sum() + df_1h["short_sig"].sum())

    r = strat_mod.run_backtest(df_1h)
    if "error" in r:
        return {"error": r["error"]}
    r["sig_before"] = sig_before
    r["sig_after"] = sig_after
    r["removed"] = round((1 - sig_after / sig_before) * 100, 1) if sig_before else 0
    return r


# ── 跑所有模式 ──
modes = [
    ("1h 基线（无过滤）", None),
    ("+ 4h regime 同向", "regime"),
    ("+ 4h RSI 同向", "rsi"),
    ("+ 4h regime 或 RSI", "either"),
    ("+ 4h regime 且 RSI", "both"),
]

print("=" * 70)
print(f"  1h 基线 + 4h 过滤 · ${INITIAL_CAPITAL:,} · {START_DATE} → {END_DATE}")
print("=" * 70)

# Baseline (no filter) — run once
strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH
strat_mod.ATR_TRAIL_MULT = 4.2
strategy_clean = lambda: (
    setattr(strat_mod, "FUNDING_RATE", C.FUNDING_RATE_1H_ETH),
    setattr(strat_mod, "ATR_TRAIL_MULT", 4.2),
    setattr(strat_mod, "MR_ATR_STOP_MULT", 5.2),
)

df_1h_base = strat_mod.load_data(ROOT / "data" / "eth_usdt_1h.csv")
if df_1h_base.index.tz is not None:
    df_1h_base.index = df_1h_base.index.tz_localize(None)
df_1h_base = df_1h_base[(df_1h_base.index >= START_DATE) & (df_1h_base.index < END_DATE)].copy()
df_1h_base = strat_mod.compute_signals(df_1h_base)
baseline_r = strat_mod.run_backtest(df_1h_base)

print(f"\n  {'Config':<28} {'Final':>10} {'PNL':>10} {'Ret':>8} {'Sharpe':>8} {'DD':>7} {'Trades':>6} {'Win%':>6} {'PF':>6} {'Liq':>4}  {'Signals':<14}")
print("  " + "-" * 107)

for label, mode in modes:
    if mode is None:
        r = baseline_r
        sig_info = "—"
    else:
        r = run_1h_with_4h_filter(mode)
        if "error" in r:
            print(f"  {label:<28} ERROR: {r['error']}")
            continue
        sig_info = f"{r['sig_after']}/{r['sig_before']} (-{r['removed']}%)"

    final = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
    print(f"  {label:<28} ${final:>8,.0f} ${final-INITIAL_CAPITAL:>+8,.0f} "
          f"{r['total_return']:>+7.1f}% {r['sharpe_ratio']:>8.3f} "
          f"{r['max_drawdown']:>6.1f}% {r['num_trades']:>6} "
          f"{r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} "
          f"{r['liquidations']:>4}  {sig_info:<14}")

print()

# 最佳配置 → 全周期
best_mode = "either"
print("=" * 70)
print(f"  Full Cycle 跑最佳配置 (1h + 4h regime 或 RSI)")
print("=" * 70)

strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH
df_1h_all = strat_mod.load_data(ROOT / "data" / "eth_usdt_1h.csv")
df_4h_all = strat_mod.load_data(ROOT / "data" / "eth_usdt_4h.csv")
for d in [df_1h_all, df_4h_all]:
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
df_1h_all = strat_mod.compute_signals(df_1h_all)

df_4h_f = calc_4h_adx_rsi(df_4h_all)
df_4h_1h_f = df_4h_f.reindex(df_1h_all.index, method="ffill")
df_1h_all = pd.concat([df_1h_all, df_4h_1h_f], axis=1)

removed = 0
for i in range(len(df_1h_all)):
    row = df_1h_all.iloc[i]
    rsi4 = row.get("rsi_4h", np.nan)
    trend4 = row.get("is_trend_4h", 0)
    if pd.isna(rsi4):
        df_1h_all.iloc[i, df_1h_all.columns.get_loc("long_sig")] = False
        df_1h_all.iloc[i, df_1h_all.columns.get_loc("short_sig")] = False
        continue
    if bool(row["long_sig"]) and not (bool(trend4) or rsi4 < 50):
        df_1h_all.iloc[i, df_1h_all.columns.get_loc("long_sig")] = False
        removed += 1
    if bool(row["short_sig"]) and not (bool(trend4) or rsi4 > 50):
        df_1h_all.iloc[i, df_1h_all.columns.get_loc("short_sig")] = False
        removed += 1

r_best = strat_mod.run_backtest(df_1h_all)
if "error" not in r_best:
    final = INITIAL_CAPITAL * (1 + r_best["total_return"] / 100)
    print(f"  Final: ${final:,.0f}  Ret {r_best['total_return']:+.1f}%  Ann {r_best['annual_return']:+.1f}%")
    print(f"  Sharpe: {r_best['sharpe_ratio']:.3f}  DD: {r_best['max_drawdown']:.1f}%  Calmar: {r_best['calmar_ratio']:.3f}")
    print(f"  Trades: {r_best['num_trades']} (L:{r_best['long_trades']} S:{r_best['short_trades']})")
    print(f"  Win: {r_best['win_rate']}%  PF: {r_best['profit_factor']}  Liq: {r_best['liquidations']}")
    print(f"  Bench B&H: {r_best['benchmark_return']:+.1f}%  Excess: {r_best['excess_return']:+.1f}%")
    print()

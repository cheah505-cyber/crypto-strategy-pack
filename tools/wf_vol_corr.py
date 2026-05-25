"""Walk-Forward: 4h baseline + vol_price_corr > 0 filter."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals
import backtests.adx_adaptive_perp_eth_4h as strat_mod

DATA_PATH = ROOT / "data" / "eth_usdt_4h.csv"

strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

WF_WINDOW = 8
WF_STEP = 4
MIN_TRADES = 5
ATR_GRID = [1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0]


def vol_price_corr(close: pd.Series, volume: pd.Series, w: int = 20) -> pd.Series:
    return close.rolling(w).corr(volume)


def run_params(df: pd.DataFrame, atr_m: float) -> dict | None:
    strat_mod.ATR_TRAIL_MULT = atr_m
    strat_mod.MR_ATR_STOP_MULT = atr_m + 1.0
    strat_mod.ADX_TREND = 30
    strat_mod.ADX_RANGE = 15

    dft = df.copy()
    dft = compute_signals(dft)
    # 量价一致过滤
    corr = vol_price_corr(dft["close"], dft["volume"], 20)
    mask = corr.fillna(0) <= 0
    dft.loc[mask, "long_sig"] = False
    dft.loc[mask, "short_sig"] = False

    r = strat_mod.run_backtest(dft)
    if "error" in r or r["num_trades"] < MIN_TRADES:
        return None
    return r


# ── 全周期 ──
print("=" * 80)
print("  4h + vol_price_corr>0 — Full Cycle (2019-2026)")
print("=" * 80)

df_full = load_data(DATA_PATH)
if df_full.index.tz is not None:
    df_full.index = df_full.index.tz_localize(None)

r_full = run_params(df_full.copy(), atr_m=2.5)
if r_full:
    print(f"  Ret {r_full['total_return']:+.1f}%  Sharpe {r_full['sharpe_ratio']:.3f}  "
          f"DD {r_full['max_drawdown']:.1f}%  Trades {r_full['num_trades']}  "
          f"Win {r_full['win_rate']}%  PF {r_full['profit_factor']}  Liq {r_full['liquidations']}")
print()

# ── Walk-Forward ──
print("=" * 80)
print("  Walk-Forward: 8m IS / 4m OOS")
print("=" * 80)

start_dates = pd.date_range(
    start=df_full.index.min(),
    end=df_full.index.max() - pd.DateOffset(months=WF_WINDOW + WF_STEP),
    freq=pd.DateOffset(months=WF_STEP),
)

windows = []
cum_eq = 1.0

for i, ws in enumerate(start_dates):
    is_start = ws
    is_end = ws + pd.DateOffset(months=WF_WINDOW)
    oos_end = is_end + pd.DateOffset(months=WF_STEP)
    if oos_end > df_full.index.max():
        break

    df_is = df_full[(df_full.index >= is_start) & (df_full.index < is_end)].copy()
    df_oos = df_full[(df_full.index >= is_end) & (df_full.index < oos_end)].copy()
    if len(df_is) < 200 or len(df_oos) < 100:
        continue

    best_atr = None
    best_sh = -999
    for atr_m in ATR_GRID:
        r = run_params(df_is, atr_m)
        if r and r["sharpe_ratio"] > best_sh:
            best_sh = r["sharpe_ratio"]
            best_atr = atr_m
    if best_atr is None:
        continue

    r_oos = run_params(df_oos, best_atr)
    if r_oos is None:
        continue

    cum_eq *= (1 + r_oos["total_return"] / 100)
    windows.append({
        "oos_period": f"{is_end.date()}→{oos_end.date()}",
        "best_atr": best_atr,
        "is_sh": best_sh,
        "oos_ret": r_oos["total_return"],
        "oos_sh": r_oos["sharpe_ratio"],
        "oos_dd": r_oos["max_drawdown"],
        "oos_trades": r_oos["num_trades"],
        "oos_pf": r_oos["profit_factor"],
        "liqs": r_oos["liquidations"],
    })

if not windows:
    print("  No valid windows")
    sys.exit(1)

print(f"  {'OOS Period':<22} {'ATR':<5} {'OOS Ret':>8} {'OOS Sh':>7} {'DD':>7} {'PF':>6} {'Trades':>6} {'Liq':>4}")
print("  " + "-" * 73)
for w in windows:
    print(f"  {w['oos_period']:<22} {w['best_atr']:<5.1f}x {w['oos_ret']:>+7.1f}% "
          f"{w['oos_sh']:>7.3f} {w['oos_dd']:>6.1f}% {w['oos_pf']:>5.2f} "
          f"{w['oos_trades']:>6} {w['liqs']:>4}")

total = len(windows)
positive = sum(1 for w in windows if w["oos_ret"] > 0)
cum_ret = (cum_eq - 1) * 100

print(f"\n  Positive OOS: {positive}/{total} ({positive/total*100:.0f}%)")
print(f"  Cumulative OOS: {cum_ret:+.2f}%")
print(f"  Zero liqs: {'YES' if sum(w['liqs'] for w in windows) == 0 else 'NO'}")
print()

# 与基线对比
print(f"  4h 基线 WF: 12/19 (63%)  cum +316%")
print()

if positive / total >= 0.6 and cum_ret > 0:
    print("  === PASS ===")
elif cum_ret > 0:
    print("  === WARN ===")
else:
    print("  === FAIL ===")
print()

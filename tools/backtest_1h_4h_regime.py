"""1h + 4h regime 同向：全周期回测 + Walk-Forward。"""
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

# ── 参数 ──
strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 4.2
strat_mod.MR_ATR_STOP_MULT = 5.2
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def load_data_1h_4h() -> tuple[pd.DataFrame, pd.DataFrame]:
    df1h = strat_mod.load_data(ROOT / "data" / "eth_usdt_1h.csv")
    df4h = strat_mod.load_data(ROOT / "data" / "eth_usdt_4h.csv")
    for d in [df1h, df4h]:
        if d.index.tz is not None:
            d.index = d.index.tz_localize(None)
    return df1h, df4h


def compute_4h_regime(df_4h: pd.DataFrame) -> pd.DataFrame:
    """计算 4h ADX + 趋势标记。"""
    df = df_4h.copy()
    c, h, l = df["close"], df["high"], df["low"]
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
    return df[["adx_4h"]]


def apply_regime_filter(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> pd.DataFrame:
    """4h regime 同向过滤。"""
    df_4h_regime = compute_4h_regime(df_4h)
    df_4h_aligned = df_4h_regime.reindex(df_1h.index, method="ffill")
    df_1h = pd.concat([df_1h, df_4h_aligned], axis=1)

    kept = 0
    for i in range(len(df_1h)):
        row = df_1h.iloc[i]
        adx4 = row.get("adx_4h", np.nan)
        in_trend = not pd.isna(adx4) and adx4 > 30

        if bool(row["long_sig"]) and not in_trend:
            df_1h.iloc[i, df_1h.columns.get_loc("long_sig")] = False
        else:
            kept += 1 if bool(row["long_sig"]) else 0

        if bool(row["short_sig"]) and not in_trend:
            df_1h.iloc[i, df_1h.columns.get_loc("short_sig")] = False
        else:
            kept += 1 if bool(row["short_sig"]) else 0

    return df_1h


def run_backtest_1h_regime() -> dict:
    df1h, df4h = load_data_1h_4h()
    df1h = strat_mod.compute_signals(df1h)
    df1h = apply_regime_filter(df1h, df4h)
    return strat_mod.run_backtest(df1h)


# ── 1. 全周期回测 ──
print("=" * 70)
print("  1h + 4h regime 同向 — Full Cycle Backtest")
print("=" * 70)

r = run_backtest_1h_regime()
if "error" in r:
    print(f"  ERROR: {r['error']}")
    sys.exit(1)

final = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
print(f"  Data: 2023-01-01 → 2026-05-21 (29,686 bars)")
print(f"  Final: ${final:,.0f}  Ret {r['total_return']:+.1f}%  Ann {r['annual_return']:+.1f}%")
print(f"  Sharpe: {r['sharpe_ratio']:.3f}  DD: {r['max_drawdown']:.1f}%  Calmar: {r['calmar_ratio']:.3f}")
print(f"  Trades: {r['num_trades']} (L:{r['long_trades']} S:{r['short_trades']})")
print(f"  Win: {r['win_rate']}%  PF: {r['profit_factor']}  Stops: {r['stop_outs']}  Liq: {r['liquidations']}")
print(f"  Bench B&H: {r['benchmark_return']:+.1f}%  Excess: {r['excess_return']:+.1f}%")
print()

# ── 2. Walk-Forward ──
print("=" * 70)
print("  Walk-Forward: 4m IS / 2m OOS (step 2m)")
print("=" * 70)

WF_WINDOW = 4
WF_STEP = 2
WF_MIN_TRADES = 8
ATR_GRID = [3.0, 3.5, 4.0, 4.2, 4.5, 5.0, 5.5]

df1h_full, df4h_full = load_data_1h_4h()

start_dates = pd.date_range(
    start=df1h_full.index.min() + pd.DateOffset(months=WF_WINDOW),
    end=df1h_full.index.max() - pd.DateOffset(months=WF_STEP),
    freq=pd.DateOffset(months=WF_STEP),
)

windows = []
cum_eq = 1.0

for i, wf_start in enumerate(start_dates):
    oos_start = wf_start
    oos_end = wf_start + pd.DateOffset(months=WF_STEP)

    # 做 IS 和 OOS 窗口要用完整数据范围，因为 4h align 需要前向填充
    wf_start_full = wf_start - pd.DateOffset(months=WF_WINDOW)

    is_1h = df1h_full[(df1h_full.index >= wf_start_full) & (df1h_full.index < oos_start)].copy()
    oos_1h = df1h_full[(df1h_full.index >= oos_start) & (df1h_full.index < oos_end)].copy()
    # 4h 需要覆盖 IS+OOS 甚至更前（ffill 需要）
    wf_4h = df4h_full[df4h_full.index < oos_end].copy()

    if len(is_1h) < 500 or len(oos_1h) < 200:
        continue

    best_atr = None
    best_sh = -999

    # IS 优化
    is_sig = strat_mod.compute_signals(is_1h)
    is_filtered = apply_regime_filter(is_sig, wf_4h)

    for atr_m in ATR_GRID:
        strat_mod.ATR_TRAIL_MULT = atr_m
        strat_mod.MR_ATR_STOP_MULT = atr_m + 1.0
        rr = strat_mod.run_backtest(is_filtered.copy())
        if rr and "error" not in rr and rr["num_trades"] >= WF_MIN_TRADES and rr["sharpe_ratio"] > best_sh:
            best_sh = rr["sharpe_ratio"]
            best_atr = atr_m

    if best_atr is None:
        continue

    # OOS 测试
    strat_mod.ATR_TRAIL_MULT = best_atr
    strat_mod.MR_ATR_STOP_MULT = best_atr + 1.0
    oos_sig = strat_mod.compute_signals(oos_1h)
    oos_filtered = apply_regime_filter(oos_sig, wf_4h)
    rr_oos = strat_mod.run_backtest(oos_filtered)
    if rr_oos is None or "error" in rr_oos:
        continue

    cum_eq *= (1 + rr_oos["total_return"] / 100)
    windows.append({
        "oos_period": f"{oos_start.date()}→{oos_end.date()}",
        "best_atr": best_atr,
        "is_sh": best_sh,
        "oos_ret": rr_oos["total_return"],
        "oos_sh": rr_oos["sharpe_ratio"],
        "oos_dd": rr_oos["max_drawdown"],
        "oos_trades": rr_oos["num_trades"],
        "oos_pf": rr_oos["profit_factor"],
        "liqs": rr_oos["liquidations"],
    })

if not windows:
    print("  No valid windows")
else:
    print(f"  Windows: {len(windows)}")
    print(f"  {'OOS Period':<22} {'ATR':<5} {'OOS Ret':>8} {'OOS Sh':>7} {'DD':>7} {'PF':>6} {'Trades':>6} {'Liq':>4}")
    print("  " + "-" * 73)
    for w in windows:
        print(f"  {w['oos_period']:<22} {w['best_atr']:<5.1f}x {w['oos_ret']:>+7.1f}% {w['oos_sh']:>7.3f} {w['oos_dd']:>6.1f}% {w['oos_pf']:>5.2f} {w['oos_trades']:>6} {w['liqs']:>4}")

    pos = sum(1 for w in windows if w["oos_ret"] > 0)
    cum_pct = (cum_eq - 1) * 100
    print(f"\n  Positive OOS: {pos}/{len(windows)} ({pos/len(windows)*100:.0f}%)")
    print(f"  Cumulative OOS: {cum_pct:+.2f}% (equity {cum_eq:.4f}x)")
    print(f"  Zero liqs: {'YES' if sum(w['liqs'] for w in windows) == 0 else 'NO'}")
    verdict = "PASS" if pos / len(windows) >= 0.6 and cum_pct > 0 else "WARN" if cum_pct > 0 else "FAIL"
    print(f"  === {verdict} ===")

print()

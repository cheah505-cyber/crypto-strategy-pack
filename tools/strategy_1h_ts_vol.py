"""1h 时序类+成交量类组合策略。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "utils"))
import constants as C

INITIAL = 10_000
DATA_PATH = ROOT / "data" / "eth_usdt_1h.csv"
FEE = C.FEE_TAKER; SLIPPAGE = C.SLIPPAGE_ETH; FUNDING_RATE = C.FUNDING_RATE_1H_ETH


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    # ── 效率比 (Kaufman ER) ──
    for period in [6, 12, 24]:
        direction = (c - c.shift(period)).abs()
        volatility = (c - c.shift(1)).abs().rolling(period).sum()
        d[f"er_{period}"] = direction / volatility.replace(0, np.nan)

    # ── 序列自相关 (return autocorrelation) ──
    ret = c.pct_change()
    for lag in [1, 3, 6, 12]:
        d[f"autocorr_{lag}"] = ret.rolling(24).corr(ret.shift(lag))

    # ── 时序动量 (不同窗口的累收益) ──
    for period in [6, 12, 24, 48]:
        d[f"ts_mom_{period}"] = c.pct_change(period)

    # ── 成交量因子 ──
    d["vol_ma"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d["vol_ma"].replace(0, np.nan)
    d["vol_price_corr"] = c.rolling(20).corr(v)

    return d


def run_backtest(df: pd.DataFrame, long_cond: pd.Series, short_cond: pd.Series, name: str) -> dict:
    eq = float(INITIAL); equity = [eq]; peak = eq; max_dd = 0
    trades = []; pos = 0; entry_eq = eq; entry_px = 0; contracts = 0
    cl = 0; cd = -1

    for i in range(len(df)):
        row = df.iloc[i]; px = float(row["close"])
        atr = float(row.get("atr", 0) or 0) or px * 0.02
        in_cd = i < cd

        # 固定 ATR 止损 3.0x
        if pos != 0:
            stop = (pos == 1 and px < (entry_px - atr * 3.0)) or (pos == -1 and px > (entry_px + atr * 3.0))
            if stop:
                pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if pos==1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
                ret = pnl/entry_eq
                trades[-1]["exit_reason"] = "stop"; trades[-1]["exit_price"] = px; trades[-1]["return"] = ret; trades[-1]["exit_time"] = df.index[i]
                new_eq = max(entry_eq+pnl, 0.0001); equity.append(new_eq)
                peak = max(peak, new_eq); max_dd = max(max_dd, (peak-new_eq)/peak if peak>0 else 0)
                cl = cl+1 if ret<=0 else 0
                if cl >= 5: cd = i + 24
                pos = 0; continue

        if pos == 0 and not in_cd:
            if bool(long_cond.iloc[i]):
                pos = 1
                risk = equity[-1] * 0.04
                contracts = min(risk/(atr*3.0/px), equity[-1]*10)/px
                entry_px = px*(1+SLIPPAGE)*(1+FEE); entry_eq = equity[-1]
                trades.append({"entry_time": df.index[i], "side": "LONG", "exit_reason": None, "return": None})
                equity.append(equity[-1]); continue
            elif bool(short_cond.iloc[i]):
                pos = -1
                risk = equity[-1] * 0.04
                contracts = min(risk/(atr*3.0/px), equity[-1]*10)/px
                entry_px = px*(1-SLIPPAGE)*(1-FEE); entry_eq = equity[-1]
                trades.append({"entry_time": df.index[i], "side": "SHORT", "exit_reason": None, "return": None})
                equity.append(equity[-1]); continue

        if pos != 0:
            prev = float(df.iloc[i-1]["close"])
            pnl = contracts*(px-prev) if pos==1 else contracts*(prev-px)
            equity.append(equity[-1]+pnl-(contracts*px)*FUNDING_RATE)
            peak = max(peak, equity[-1]); max_dd = max(max_dd, (peak-equity[-1])/peak if peak>0 else 0)
        else:
            equity.append(equity[-1])

    if pos != 0:
        pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if pos==1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
        trades[-1]["exit_reason"] = "eod"; trades[-1]["exit_price"] = px; trades[-1]["return"] = pnl/entry_eq; trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_eq+pnl, 0.0001)

    comp = [t for t in trades if t["return"] is not None]
    rets = [t["return"] for t in comp]
    w = [r for r in rets if r>0]; l_ = [r for r in rets if r<=0]
    tr = float(equity[-1]/INITIAL-1)*100; ny = max((df.index[-1]-df.index[0]).days/365.25, 0.01)
    ann = ((1+tr/100)**(1/ny)-1)*100 if tr>-100 else -100
    eq_s = pd.Series(equity[:len(df)], index=df.index)
    ps = eq_s.expanding().max(); dd_s = (ps-eq_s)/ps; mdd = float(dd_s.max())*100
    dr = eq_s.pct_change().dropna()
    sh = ann/(float(dr.std()*np.sqrt(365.25))*100+0.001) if len(dr)>1 else 0
    longs = len([t for t in comp if t["side"]=="LONG"])
    shorts = len([t for t in comp if t["side"]=="SHORT"])
    return {"name": name, "total_return": round(tr,2), "annual_return": round(ann,2), "max_drawdown": round(mdd,2), "sharpe_ratio": round(sh,3), "num_trades": len(comp), "win_rate": round(len(w)/len(comp)*100,1) if comp else 0, "profit_factor": round(abs(sum(w)/sum(l_)),2) if w and sum(l_)!=0 else 0, "liquidations": 0, "long_trades": longs, "short_trades": shorts}


# ── 主测试 ──
print("=" * 80)
print("  1h 时序类+成交量类 策略测试")
print("=" * 80)

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
if df.index.tz is not None: df.index = df.index.tz_localize(None)

# ATR 要做止损用
tr1 = (df["high"]-df["low"]).abs(); tr2 = (df["high"]-df["close"].shift()).abs(); tr3 = (df["low"]-df["close"].shift()).abs()
df["atr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).ewm(alpha=1/14, min_periods=14).mean()

for label, start, end in [("2023-2026", "2023-01-01", "2026-05-25"), ("前测2025", "2025-06-01", "2026-05-25")]:
    d = df[(df.index >= start) & (df.index < end)].copy()
    d = compute_features(d)
    print(f"\n  {label}:")
    print(f"  {'策略':<28} {'Final':>10} {'Ret':>8} {'Sharpe':>8} {'DD':>7} {'Trades':>6} {'L/S':<6} {'Win%':>6} {'PF':>6}")
    print("  " + "-" * 85)

    tests = []

    # 1. 效率比趋势 (ER>0.5 = 强趋势)
    er_long = (d["er_12"].fillna(0) > 0.5) & (d["ts_mom_12"].fillna(0) > 0.02)
    er_short = (d["er_12"].fillna(0) > 0.5) & (d["ts_mom_12"].fillna(0) < -0.02)
    tests.append(run_backtest(d, er_long, er_short, "效率比>0.5+动量>2%"))

    # 2. 效率比 + 量价一致
    er_vc_long = er_long & (d["vol_price_corr"].fillna(0) > 0.3)
    er_vc_short = er_short & (d["vol_price_corr"].fillna(0) > 0.3)
    tests.append(run_backtest(d, er_vc_long, er_vc_short, "效率比+量价一致>0.3"))

    # 3. 序列自相关负→做反转 (autocorr<0 = 均值回归)
    ac_long = (d["autocorr_3"].fillna(0) < -0.3) & (d["ts_mom_6"].fillna(0) < -0.01)
    ac_short = (d["autocorr_3"].fillna(0) < -0.3) & (d["ts_mom_6"].fillna(0) > 0.01)
    tests.append(run_backtest(d, ac_long, ac_short, "自相关<-0.3+反转"))

    # 4. 序列自相关正→做趋势
    ac_t_long = (d["autocorr_6"].fillna(0) > 0.3) & (d["ts_mom_12"].fillna(0) > 0.02)
    ac_t_short = (d["autocorr_6"].fillna(0) > 0.3) & (d["ts_mom_12"].fillna(0) < -0.02)
    tests.append(run_backtest(d, ac_t_long, ac_t_short, "自相关>0.3+趋势"))

    # 5. 纯时序动量 24h + 量价一致
    mom_long = (d["ts_mom_24"].fillna(0) > 0.03) & (d["vol_price_corr"].fillna(0) > 0.3) & (d["vol_ratio"].fillna(0) > 1.2)
    mom_short = (d["ts_mom_24"].fillna(0) < -0.03) & (d["vol_price_corr"].fillna(0) > 0.3) & (d["vol_ratio"].fillna(0) > 1.2)
    tests.append(run_backtest(d, mom_long, mom_short, "24h动量>3%+量价+放量"))

    # 6. ER 无方向 — 只在强趋势时做，方向由多空决定
    er_dir_long = (d["er_12"].fillna(0) > 0.6) & (d["close"] > d["close"].rolling(24).mean())
    er_dir_short = (d["er_12"].fillna(0) > 0.6) & (d["close"] < d["close"].rolling(24).mean())
    tests.append(run_backtest(d, er_dir_long, er_dir_short, "ER>0.6+价格均线方向"))

    for r in tests:
        final = INITIAL * (1 + r["total_return"]/100)
        ls = f"{r['long_trades']}/{r['short_trades']}"
        print(f"  {r['name']:<28} ${final:>8,.0f} {r['total_return']:>+7.1f}% "
              f"{r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>6.1f}% {r['num_trades']:>6} "
              f"{ls:<6} {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

print()
print(f"  4h 基线 (vol_corr>0):  Sharpe 1.414  DD 24.7%")
print()

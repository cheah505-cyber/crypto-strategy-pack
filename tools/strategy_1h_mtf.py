"""1h 多时框趋势过滤 — 多种过滤模式对比。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))
import constants as C

INITIAL = 10_000
FEE = C.FEE_TAKER; SLIPPAGE = C.SLIPPAGE_ETH; FUNDING_RATE = C.FUNDING_RATE_1H_ETH
MAX_LEV = 10.0; RISK = 0.04; ATR_MULT = 3.0


def ema_slope(series, period=20):
    ema = series.ewm(span=period).mean()
    return ema.pct_change(period)


print("=" * 80)
print("  1h 多时框趋势过滤 — 对比全部模式")
print("=" * 80)

# 加载数据
df_1h = pd.read_csv(ROOT/"data"/"eth_usdt_1h.csv", parse_dates=["timestamp"], index_col="timestamp")
df_4h = pd.read_csv(ROOT/"data"/"eth_usdt_4h.csv", parse_dates=["timestamp"], index_col="timestamp")
df_1d = pd.read_csv(ROOT/"data"/"eth_usdt_1d.csv", parse_dates=["timestamp"], index_col="timestamp")
for d in [df_1h, df_4h, df_1d]:
    if d.index.tz is not None: d.index = d.index.tz_localize(None)

# 计算趋势方向
d_slope = ema_slope(df_1d["close"], 20)
f_slope = ema_slope(df_4h["close"], 20)
h_slope = ema_slope(df_1h["close"], 20)

daily_up = (d_slope > 0.001).reindex(df_1h.index, method="ffill").fillna(False)
daily_down = (d_slope < -0.001).reindex(df_1h.index, method="ffill").fillna(False)
fourh_up = (f_slope > 0.001).reindex(df_1h.index, method="ffill").fillna(False)
fourh_down = (f_slope < -0.001).reindex(df_1h.index, method="ffill").fillna(False)

# 1h 信号: EMA 金叉/死叉 + 突破
c = df_1h["close"]
ema12 = c.ewm(span=12).mean(); ema26 = c.ewm(span=26).mean()
df_1h["long_sig"] = (ema12 > ema26) & (ema12.shift(1) <= ema26.shift(1))
df_1h["short_sig"] = (ema12 < ema26) & (ema12.shift(1) >= ema26.shift(1))
df_1h["atr"] = pd.concat([
    df_1h["high"]-df_1h["low"], (df_1h["high"]-df_1h["close"].shift()).abs(),
    (df_1h["low"]-df_1h["close"].shift()).abs()
], axis=1).max(axis=1).ewm(alpha=1/14, min_periods=14).mean()

# 过滤模式
filters = {
    "无过滤": (pd.Series(True, index=df_1h.index), pd.Series(True, index=df_1h.index)),
    "日线方向": (daily_up, daily_down),
    "4h方向": (fourh_up, fourh_down),
    "日线+4h一致": (daily_up & fourh_up, daily_down & fourh_down),
    "日线或4h": (daily_up | fourh_up, daily_down | fourh_down),
}


def run_bt(df: pd.DataFrame, up_filter: pd.Series, down_filter: pd.Series) -> dict:
    eq = float(INITIAL); equity = [eq]; peak = eq; max_dd = 0
    trades = []; pos = 0; entry_eq = eq; entry_px = 0; contracts = 0
    cl = 0; cd = -1

    for i in range(len(df)):
        row = df.iloc[i]; px = float(row["close"])
        atr = float(row.get("atr", 0) or 0) or px * 0.02
        in_cd = i < cd

        if pos != 0:
            stop = (pos==1 and px<(entry_px-atr*ATR_MULT)) or (pos==-1 and px>(entry_px+atr*ATR_MULT))
            if stop:
                pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if pos==1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
                ret = pnl/entry_eq
                trades[-1]["exit_reason"]="stop"; trades[-1]["exit_price"]=px; trades[-1]["return"]=ret; trades[-1]["exit_time"]=df.index[i]
                new_eq = max(entry_eq+pnl,0.0001); equity.append(new_eq)
                peak = max(peak,new_eq); max_dd = max(max_dd,(peak-new_eq)/peak if peak>0 else 0)
                cl = cl+1 if ret<=0 else 0
                if cl>=5: cd = i+24
                pos = 0; continue

        if pos == 0 and not in_cd:
            if bool(row["long_sig"]) and bool(up_filter.iloc[i]):
                pos = 1; contracts = min(eq*RISK/(atr*ATR_MULT/px), eq*MAX_LEV)/px
                entry_px = px*(1+SLIPPAGE)*(1+FEE); entry_eq = eq
                trades.append({"entry_time":df.index[i],"side":"LONG","return":None})
                equity.append(eq); continue
            elif bool(row["short_sig"]) and bool(down_filter.iloc[i]):
                pos = -1; contracts = min(eq*RISK/(atr*ATR_MULT/px), eq*MAX_LEV)/px
                entry_px = px*(1-SLIPPAGE)*(1-FEE); entry_eq = eq
                trades.append({"entry_time":df.index[i],"side":"SHORT","return":None})
                equity.append(eq); continue

        if pos != 0:
            prev = float(df.iloc[i-1]["close"])
            pnl = contracts*(px-prev) if pos==1 else contracts*(prev-px)
            equity.append(equity[-1]+pnl-(contracts*px)*FUNDING_RATE)
            eq = equity[-1]; peak = max(peak,eq); max_dd = max(max_dd,(peak-eq)/peak if peak>0 else 0)
        else:
            equity.append(eq)

    if pos != 0:
        pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if pos==1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
        trades[-1]["exit_reason"]="eod"; trades[-1]["exit_price"]=px; trades[-1]["return"]=pnl/entry_eq; trades[-1]["exit_time"]=df.index[-1]
        equity[-1] = max(entry_eq+pnl,0.0001)

    comp = [t for t in trades if t["return"] is not None]
    rets = [t["return"] for t in comp]
    w = [r for r in rets if r>0]; l_ = [r for r in rets if r<=0]
    tr = float(equity[-1]/INITIAL-1)*100; ny = max((df.index[-1]-df.index[0]).days/365.25,0.01)
    ann = ((1+tr/100)**(1/ny)-1)*100 if tr>-100 else -100
    eq_s = pd.Series(equity[:len(df)], index=df.index)
    ps = eq_s.expanding().max(); dd_s = (ps-eq_s)/ps; mdd = float(dd_s.max())*100
    dr = eq_s.pct_change().dropna()
    sh = ann/(float(dr.std()*np.sqrt(365.25))*100+0.001) if len(dr)>1 else 0
    return {"total_return": round(tr,2), "annual_return": round(ann,2), "max_drawdown": round(mdd,2), "sharpe_ratio": round(sh,3), "num_trades": len(comp), "win_rate": round(len(w)/len(comp)*100,1) if comp else 0, "profit_factor": round(abs(sum(w)/sum(l_)),2) if w and sum(l_)!=0 else 0, "liquidations": 0, "long_trades": len([t for t in comp if t["side"]=="LONG"]), "short_trades": len([t for t in comp if t["side"]=="SHORT"])}


for label, start, end in [("2023-2026", "2023-01-01", "2026-05-25"), ("前测2025", "2025-06-01", "2026-05-25")]:
    df = df_1h[(df_1h.index >= start) & (df_1h.index < end)].copy()
    print(f"\n  {label}:")
    print(f"  {'过滤模式':<20} {'Final':>10} {'Ret':>8} {'Sharpe':>8} {'DD':>7} {'Trades':>6} {'L/S':<6} {'Win%':>6} {'PF':>6} {'信号保留':>9}")
    print("  " + "-" * 86)

    for name, (up_f, down_f) in filters.items():
        uf = up_f.reindex(df.index, method="ffill") if isinstance(up_f, pd.Series) and len(up_f) > len(df) else up_f
        df_ = up_f.reindex(df.index, method="ffill") if isinstance(up_f, pd.Series) else up_f

        # 统计信号保留率
        if name != "无过滤":
            raw_l = df["long_sig"].sum() + df["short_sig"].sum()
            filt_l = (df["long_sig"] & up_f.reindex(df.index, method="ffill").fillna(False)).sum() + \
                     (df["short_sig"] & down_f.reindex(df.index, method="ffill").fillna(False)).sum()
            keep_r = filt_l / raw_l * 100 if raw_l else 0
        else:
            keep_r = 100

        r = run_bt(df, up_f.reindex(df.index, method="ffill").fillna(False) if isinstance(up_f, pd.Series) else up_f,
                   down_f.reindex(df.index, method="ffill").fillna(False) if isinstance(down_f, pd.Series) else down_f)
        final = INITIAL * (1 + r["total_return"]/100)
        ls = f"{r['long_trades']}/{r['short_trades']}"
        print(f"  {name:<20} ${final:>8,.0f} {r['total_return']:>+7.1f}% "
              f"{r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>6.1f}% {r['num_trades']:>6} "
              f"{ls:<6} {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} {keep_r:>7.0f}%")

print()
print(f"  4h 基线 (vol_corr>0): Sharpe 1.414  DD 24.7%")
print()

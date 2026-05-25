"""1h 纯波动率+成交量策略 — 无ADX，用波动扩张+放量确认做信号。"""
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

FEE = C.FEE_TAKER
SLIPPAGE = C.SLIPPAGE_ETH
FUNDING_RATE = C.FUNDING_RATE_1H_ETH
LEVERAGE = 10.0
RISK = 0.04


def compute_signal(df: pd.DataFrame) -> pd.DataFrame:
    """无ADX，只算波动率+成交量因子。"""
    d = df.copy()
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    # ATR
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, min_periods=14).mean()
    d["atr_ma"] = d["atr"].rolling(20).mean()
    d["atr_ratio"] = d["atr"] / d["atr_ma"].replace(0, np.nan)  # 波动扩张率

    # 成交量
    d["vol_ma"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d["vol_ma"].replace(0, np.nan)  # 放量率

    # 量价相关性
    d["vol_price_corr"] = c.rolling(20).corr(v)

    # 价格位置
    d["range_high"] = h.rolling(20).max()
    d["range_low"] = l.rolling(20).min()
    d["range_pos"] = (c - d["range_low"]) / (d["range_high"] - d["range_low"]).replace(0, np.nan)

    # 测试4组不同的信号组合
    configs = {
        # name: (long_cond, short_cond)
        "波动扩张+放量": (
            (d["atr_ratio"].fillna(0) > 1.3) & (d["vol_ratio"].fillna(0) > 1.5) & (d["range_pos"].fillna(0.5) > 0.7),
            (d["atr_ratio"].fillna(0) > 1.3) & (d["vol_ratio"].fillna(0) > 1.5) & (d["range_pos"].fillna(0.5) < 0.3),
        ),
        "宽松版(>1.2+>1.2)": (
            (d["atr_ratio"].fillna(0) > 1.2) & (d["vol_ratio"].fillna(0) > 1.2) & (d["range_pos"].fillna(0.5) > 0.65),
            (d["atr_ratio"].fillna(0) > 1.2) & (d["vol_ratio"].fillna(0) > 1.2) & (d["range_pos"].fillna(0.5) < 0.35),
        ),
        "量价一致突破": (
            (d["range_pos"].fillna(0.5) > 0.75) & (d["vol_price_corr"].fillna(0) > 0.3) & (d["vol_ratio"].fillna(0) > 1.3),
            (d["range_pos"].fillna(0.5) < 0.25) & (d["vol_price_corr"].fillna(0) > 0.3) & (d["vol_ratio"].fillna(0) > 1.3),
        ),
        "极端版(>1.5+>2.0)": (
            (d["atr_ratio"].fillna(0) > 1.5) & (d["vol_ratio"].fillna(0) > 2.0) & (d["range_pos"].fillna(0.5) > 0.8),
            (d["atr_ratio"].fillna(0) > 1.5) & (d["vol_ratio"].fillna(0) > 2.0) & (d["range_pos"].fillna(0.5) < 0.2),
        ),
    }

    for name, (long_cond, short_cond) in configs.items():
        d[f"long_{name}"] = long_cond
        d[f"short_{name}"] = short_cond

    return d


def run_backtest(df: pd.DataFrame, long_col: str, short_col: str) -> dict:
    trade_dir = 0; entry_px = 0.0; entry_eq = float(INITIAL)
    contracts = 0.0; equity = [float(INITIAL)]
    peak = INITIAL; max_dd = 0.0; trades = []
    consec_losses = 0; cooldown_until = -1

    for i in range(len(df)):
        row = df.iloc[i]
        px = float(row["close"])
        atr_v = float(row.get("atr", 0) or 0)
        in_cd = i < cooldown_until

        # 止损
        stop_hit = False
        if trade_dir != 0:
            if trade_dir == 1:
                stop_hit = px < (entry_px - atr_v * 3.0)
            else:
                stop_hit = px > (entry_px + atr_v * 3.0)
        if stop_hit:
            pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if trade_dir == 1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
            ret = pnl/entry_eq; trades[-1]["exit_reason"] = "stop"; trades[-1]["exit_price"] = px; trades[-1]["return"] = ret; trades[-1]["exit_time"] = df.index[i]
            new_eq = max(entry_eq+pnl, 0.0001); equity.append(new_eq); peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak-new_eq)/peak if peak>0 else 0)
            consec_losses = consec_losses+1 if ret<=0 else 0
            if consec_losses >= 5: cooldown_until = i + 24
            trade_dir = 0; continue

        # 入场
        if trade_dir == 0 and not in_cd:
            if bool(row[long_col]):
                trade_dir = 1
                if atr_v <= 0: atr_v = px * 0.02
                risk_amt = equity[-1] * RISK
                stop_dist = atr_v * 3.0
                raw = risk_amt / (stop_dist/px)
                contracts = min(raw, equity[-1]*LEVERAGE)/px
                entry_px = px*(1+SLIPPAGE)*(1+FEE); entry_eq = equity[-1]
                trades.append({"entry_time": df.index[i], "side": "LONG", "exit_reason": None, "return": None})
                equity.append(equity[-1]); continue
            elif bool(row[short_col]):
                trade_dir = -1
                if atr_v <= 0: atr_v = px * 0.02
                risk_amt = equity[-1] * RISK
                stop_dist = atr_v * 3.0
                raw = risk_amt / (stop_dist/px)
                contracts = min(raw, equity[-1]*LEVERAGE)/px
                entry_px = px*(1-SLIPPAGE)*(1-FEE); entry_eq = equity[-1]
                trades.append({"entry_time": df.index[i], "side": "SHORT", "exit_reason": None, "return": None})
                equity.append(equity[-1]); continue

        # MTM
        if trade_dir != 0:
            pnl = contracts*(px-float(df.iloc[i-1]["close"])) if trade_dir == 1 else contracts*(float(df.iloc[i-1]["close"])-px)
            equity.append(equity[-1]+pnl-(contracts*px)*FUNDING_RATE)
            peak = max(peak, equity[-1])
            max_dd = max(max_dd, (peak-equity[-1])/peak if peak>0 else 0)
        else:
            equity.append(equity[-1])

    if trade_dir != 0:
        pnl = (px*(1-SLIPPAGE)*(1-FEE)-entry_px)*contracts if trade_dir == 1 else (entry_px-px*(1+SLIPPAGE)*(1+FEE))*contracts
        trades[-1]["exit_reason"] = "eod"; trades[-1]["exit_price"] = px; trades[-1]["return"] = pnl/entry_eq; trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_eq+pnl, 0.0001)

    eq_s = pd.Series(equity[:len(df)], index=df.index)
    completed = [t for t in trades if t["return"] is not None]
    rets = [t["return"] for t in completed]; wins = [r for r in rets if r>0]; losses = [r for r in rets if r<=0]
    total_ret = float(eq_s.iloc[-1]/INITIAL-1)*100
    ny = (eq_s.index[-1]-eq_s.index[0]).days/365.25
    ann = ((1+total_ret/100)**(1/ny)-1)*100 if ny>0 and total_ret>-100 else 0
    ps = eq_s.expanding().max(); dd = (ps-eq_s)/ps; mdd = float(dd.max())*100
    dr = eq_s.pct_change().dropna(); av = float(dr.std()*np.sqrt(365.25))*100
    sh = ann/av if av>0 else 0; bm = df["close"]/df["close"].iloc[0]
    return {"total_return": round(total_ret,2), "annual_return": round(ann,2), "max_drawdown": round(mdd,2), "sharpe_ratio": round(sh,3), "num_trades": len(completed), "win_rate": round(len(wins)/len(completed)*100,1) if completed else 0, "profit_factor": round(abs(sum(wins)/sum(losses)),2) if wins and sum(losses)!=0 else 0, "liquidations": 0, "benchmark_return": round((bm.iloc[-1]-1)*100,2)}


print("=" * 70)
print("  1h 纯波动率+成交量策略 (无ADX)")
print("=" * 70)

df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
if df.index.tz is not None: df.index = df.index.tz_localize(None)

for label, start, end in [("2023-2026", "2023-01-01", "2026-05-25"), ("前测2025", "2025-06-01", "2026-05-25")]:
    d = df[(df.index >= start) & (df.index < end)].copy()
    d = compute_signal(d)
    print(f"\n  {label}:")
    print(f"  {'Config':<22} {'Final':>10} {'Ret':>8} {'Sharpe':>8} {'DD':>7} {'Trades':>6} {'Win%':>6} {'PF':>6}")
    print("  " + "-" * 73)

    configs = [
        "波动扩张+放量", "宽松版(>1.2+>1.2)", "量价一致突破", "极端版(>1.5+>2.0)"
    ]
    for cfg in configs:
        r = run_backtest(d, f"long_{cfg}", f"short_{cfg}")
        final = INITIAL * (1 + r["total_return"]/100)
        print(f"  {cfg:<22} ${final:>8,.0f} {r['total_return']:>+7.1f}% "
              f"{r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>6.1f}% {r['num_trades']:>6} "
              f"{r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

print()
print(f"  4h 基线 (vol_corr>0):  Sharpe 1.414  DD 24.7%")
print()

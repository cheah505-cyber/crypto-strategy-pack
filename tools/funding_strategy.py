"""资金费率策略：极端 funding 时反向开仓。

逻辑：
  高 funding（过热）→ 做空
  低 funding（恐慌）→ 做多
  回归均值 → 平仓

数据：Binance ETH/USDT:USDT 真实 funding rate (2019-2026, 7,113 条记录)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C

INITIAL_CAPITAL = 10_000
DATA_DIR = ROOT / "data"

# ── 加载数据 ──
def load_data() -> pd.DataFrame:
    fr = pd.read_csv(DATA_DIR / "eth_usdt_funding_rate.csv", parse_dates=["timestamp"])
    fr = fr.set_index("timestamp").sort_index()
    if fr.index.tz is not None:
        fr.index = fr.index.tz_localize(None)

    eth = pd.read_csv(DATA_DIR / "eth_usdt_4h.csv", parse_dates=["timestamp"], index_col="timestamp")
    if eth.index.tz is not None:
        eth.index = eth.index.tz_localize(None)

    # 对齐：funding rate 每 8h → 4h 前向填充
    fr_4h = fr["fundingRate"].resample("4h", label="right").ffill() / 2  # 8h → 4h
    df = eth.join(fr_4h.to_frame("funding"))
    df = df.dropna(subset=["funding"])
    return df


def compute_signals(df: pd.DataFrame, entry_z: float = 2.0) -> pd.DataFrame:
    """用 rolling z-score 标记极端 funding。

    entry_z: z-score 阈值（默认 2.0 = 均值±2σ）
    """
    roll = df["funding"].rolling(60)  # 60 bars = 10 days
    mean = roll.mean()
    std = roll.std().replace(0, np.nan)
    df["z_score"] = (df["funding"] - mean) / std

    df["long_sig"] = (df["z_score"] < -entry_z).astype(int)
    df["short_sig"] = (df["z_score"] > entry_z).astype(int)
    # 平仓信号：z-score 回到 0.5 以内
    df["close_long"] = (df["z_score"] > -0.5).astype(int)
    df["close_short"] = (df["z_score"] < 0.5).astype(int)

    return df


def run_backtest(df: pd.DataFrame) -> dict:
    """简单回测：资金费率策略。"""
    trades: list[dict] = []
    pos_side: int = 0
    entry_price: float = 0.0
    entry_equity: float = INITIAL_CAPITAL
    contracts: float = 0.0

    equity: list[float] = [INITIAL_CAPITAL]
    peak = INITIAL_CAPITAL
    max_dd = 0.0

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        fund = float(row.get("funding", 0))

        fee = C.FEE_TAKER
        slip = C.SLIPPAGE_ETH

        # ── 止损/平仓 ──
        if pos_side != 0:
            should_close = False
            reason = ""
            if pos_side == 1 and bool(row["close_long"]):
                should_close = True; reason = "signal"
            elif pos_side == -1 and bool(row["close_short"]):
                should_close = True; reason = "signal"

            if should_close:
                pnl = (price * (1 - slip) * (1 - fee) - entry_price) * contracts if pos_side == 1 else (entry_price - price * (1 + slip) * (1 + fee)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = reason
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                new_eq = max(entry_equity + pnl, 0.0001)
                equity.append(new_eq)
                peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
                pos_side = 0
                continue

        # ── 入场 ──
        if pos_side == 0:
            enter_long = bool(row["long_sig"])
            enter_short = bool(row["short_sig"])
            if enter_long or enter_short:
                risk_amount = equity[-1] * 0.04
                contracts = risk_amount / (price * 0.05)  # 固定 5% 止损距离
                contracts = min(contracts, equity[-1] * 10 / price)

                if enter_long:
                    pos_side = 1
                    entry_price = price * (1 + slip) * (1 + fee)
                    entry_equity = equity[-1]
                else:
                    pos_side = -1
                    entry_price = price * (1 - slip) * (1 - fee)
                    entry_equity = equity[-1]

                trades.append({
                    "entry_time": df.index[i], "entry_price": entry_price,
                    "side": "LONG" if pos_side == 1 else "SHORT",
                    "exit_reason": None, "exit_price": None, "return": None,
                })
                equity.append(equity[-1])
                continue

        # ── MTM + funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i - 1]["close"])
            pnl = contracts * (price - prev_price) if pos_side == 1 else contracts * (prev_price - price)
            funding_cost = (contracts * price) * fund
            new_eq = equity[-1] + pnl - funding_cost
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
        else:
            equity.append(equity[-1])

    if pos_side != 0:
        last_px = float(df.iloc[-1]["close"])
        pnl = (last_px * (1 - slip) * (1 - fee) - entry_price) * contracts if pos_side == 1 else (entry_price - last_px * (1 + slip) * (1 + fee)) * contracts
        ret = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = last_px
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    completed = [t for t in trades if t["return"] is not None]
    n = len(completed)
    rets = [t["return"] for t in completed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    total_ret = float(equity_series.iloc[-1] / INITIAL_CAPITAL - 1) * 100
    n_years = (equity_series.index[-1] - equity_series.index[0]).days / 365.25
    ann_ret = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else 0
    peak_s = equity_series.expanding().max()
    dd_s = (peak_s - equity_series) / peak_s
    max_dd = float(dd_s.max()) * 100
    daily_rets = equity_series.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0
    benchmark = df["close"] / df["close"].iloc[0]

    return {
        "total_return": round(total_ret, 2),
        "annual_return": round(ann_ret, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "num_trades": n,
        "win_rate": round(len(wins)/n*100, 1) if n else 0,
        "avg_return": round(np.mean(rets)*100, 2) if rets else 0,
        "profit_factor": round(abs(sum(wins)/sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "liquidations": 0,
        "benchmark_return": round((benchmark.iloc[-1] - 1) * 100, 2),
    }


# ── 跑回测 ──
print("=" * 70)
print("  资金费率策略 — Funding Rate Mean-Reversion")
print("=" * 70)

df = load_data()
print(f"  Data: {df.index[0]} → {df.index[-1]} ({len(df)} bars)")
print(f"  Funding range: {df['funding'].min()*100:.4f}% ~ {df['funding'].max()*100:.4f}%")
print(f"  Threshold: z-score > 2.0")

for z in [1.5, 2.0, 2.5]:
    df_sig = compute_signals(df.copy(), entry_z=z)
    r = run_backtest(df_sig)
    if "error" in r:
        continue
    final = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
    sigs = (df_sig["long_sig"] | df_sig["short_sig"]).sum()
    print(f"\n  z={z:.1f}  Final: \${final:>8,.0f}  Ret {r['total_return']:>+7.1f}%  "
          f"Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
          f"Trades {r['num_trades']}  Win {r['win_rate']}%  PF {r['profit_factor']}  "
          f"Signals {sigs}")

print()
print(f"  4h 基线对比:")
print(f"  Final: \$169,517  Ret +1,595%  Sharpe 1.288  DD 38.5%")
print()

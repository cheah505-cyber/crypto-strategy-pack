"""1h 专属策略 — 快速 ADX + 量价确认 + 紧止损。

针对 1h 噪声特性设计：
  - ADX 7期（不是14），更快响应
  - 量价一致过滤（已验证有效）
  - 紧 ATR 止损（3.0x 不是 4.2x）
  - RSI 宽区间（30/70 不是 35/65）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "utils"))
import constants as C

DATA_PATH = ROOT / "data" / "eth_usdt_1h.csv"
INITIAL = 10_000

# ── 1h 专用参数 ──
FEE = C.FEE_TAKER
SLIPPAGE = C.SLIPPAGE_ETH
FUNDING_RATE = C.FUNDING_RATE_1H_ETH

ADX_PERIOD = 7        # 1h 用 7 期（≈7h），比 14 期快一倍
ADX_TREND = 25        # 降低阈值，1h 趋势没那么强
ADX_RANGE = 10        # 降低区间阈值
DC_PERIOD = 12        # 更短的通道（≈12h）
ATR_PERIOD = 10
ATR_TRAIL_MULT = 3.0  # 比 4h 的 2.5x 松一点（1h 噪声大）
MR_ATR_STOP_MULT = 4.0

RSI_PERIOD = 10
RSI_OVERSOLD = 30     # 更宽区间（1h 假突破多）
RSI_OVERBOUGHT = 70

MAX_LEVERAGE = 10.0
RISK_PER_TRADE = 0.04
CB_MAX_LOSSES = 5
CB_COOLDOWN = 24


def load_data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    # ── RSI ──
    delta = c.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    df["rsi"] = 100 - 100/(1 + avg_gain/avg_loss.replace(0, np.nan))

    # ── ADX (7期) ──
    tr1, tr2, tr3 = h-l, (h-c.shift()).abs(), (l-c.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    up, down = h-h.shift(), l.shift()-l
    pdm = pd.Series(np.where((up>down)&(up>0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((down>up)&(down>0), down, 0.0), index=df.index)
    pdi = 100*(pdm.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()/atr.replace(0,np.nan))
    ndi = 100*(ndm.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()/atr.replace(0,np.nan))
    dx = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/ADX_PERIOD, min_periods=ADX_PERIOD).mean()
    df["atr"] = tr.ewm(alpha=1/ATR_PERIOD, min_periods=ATR_PERIOD).mean()

    # ── Donchian ──
    df["dc_high"] = h.rolling(DC_PERIOD).max()
    df["dc_low"] = l.rolling(DC_PERIOD).min()

    # ── 信号 ──
    df["long_trend"] = c > df["dc_high"].shift(1)
    df["short_trend"] = c < df["dc_low"].shift(1)
    df["long_mr"] = df["rsi"] < RSI_OVERSOLD
    df["short_mr"] = df["rsi"] > RSI_OVERBOUGHT

    df["is_trend"] = df["adx"] > ADX_TREND
    df["is_range"] = df["adx"] < ADX_RANGE

    df["long_sig"] = (df["is_trend"] & df["long_trend"]) | (df["is_range"] & df["long_mr"])
    df["short_sig"] = (df["is_trend"] & df["short_trend"]) | (df["is_range"] & df["short_mr"])
    df["close_sig"] = df["is_range"] & (df["rsi"] > RSI_OVERBOUGHT)
    df["cover_sig"] = df["is_range"] & (df["rsi"] < RSI_OVERSOLD)
    df["close_trend"] = df["is_trend"] & df["short_trend"]
    df["cover_trend"] = df["is_trend"] & df["long_trend"]

    # ── 量价一致过滤 ──
    corr = c.rolling(20).corr(v)
    df.loc[corr.fillna(0) <= 0, "long_sig"] = False
    df.loc[corr.fillna(0) <= 0, "short_sig"] = False

    return df


def run_backtest(df: pd.DataFrame) -> dict:
    """回测引擎（同 4h 逻辑，但用 1h 参数）。"""
    trades = []
    pos_side = 0
    entry_price = 0.0
    entry_equity = INITIAL
    contracts = 0.0
    entry_regime = ""
    trail_stop = 0.0
    hard_stop = 0.0
    equity = [float(INITIAL)]
    peak = INITIAL
    max_dd = 0.0
    consec_losses = 0
    cooldown_until = -1

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        in_cooldown = i < cooldown_until

        # ── 强平 ──
        if pos_side != 0:
            margin = (contracts * price) / MAX_LEVERAGE
            if equity[-1] <= 0 or (margin > 0 and equity[-1] < margin * 0.10):
                pnl = (price * (1-SLIPPAGE)*(1-FEE) - entry_price) * contracts if pos_side == 1 else (entry_price - price * (1+SLIPPAGE)*(1+FEE)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = "liquidated"
                trades[-1]["exit_price"] = price; trades[-1]["return"] = ret; trades[-1]["exit_time"] = df.index[i]
                equity[-1] = max(entry_equity + pnl, 0.0001)
                peak = max(peak, equity[-1]); max_dd = max(max_dd, (peak - equity[-1]) / peak)
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                if consec_losses >= CB_MAX_LOSSES: cooldown_until = i + CB_COOLDOWN
                pos_side = 0; continue

        # ── 止损 ──
        if pos_side != 0:
            stop_hit = False; reason = ""
            if pos_side == 1:
                if price < trail_stop: stop_hit = True; reason = "trail"
                elif bool(row["close_sig"]) or bool(row["close_trend"]): stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price < hard_stop: stop_hit = True; reason = "hard"
            else:
                if price > trail_stop: stop_hit = True; reason = "trail"
                elif bool(row["cover_sig"]) or bool(row["cover_trend"]): stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price > hard_stop: stop_hit = True; reason = "hard"

            if stop_hit:
                pnl = (price * (1-SLIPPAGE)*(1-FEE) - entry_price) * contracts if pos_side == 1 else (entry_price - price * (1+SLIPPAGE)*(1+FEE)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = reason; trades[-1]["exit_price"] = price; trades[-1]["return"] = ret; trades[-1]["exit_time"] = df.index[i]
                new_eq = max(entry_equity + pnl, 0.0001)
                equity.append(new_eq); peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                if consec_losses >= CB_MAX_LOSSES: cooldown_until = i + CB_COOLDOWN
                pos_side = 0; continue

        # ── 入场 ──
        if pos_side == 0 and not in_cooldown:
            if bool(row["long_sig"]) or bool(row["short_sig"]):
                if atr_val <= 0: atr_val = price * 0.02
                risk_amount = equity[-1] * RISK_PER_TRADE
                stop_dist = atr_val * ATR_TRAIL_MULT
                raw_value = risk_amount / (stop_dist / price)
                lev_value = equity[-1] * MAX_LEVERAGE
                contracts = min(raw_value, lev_value) / price

                if bool(row["long_sig"]):
                    pos_side = 1; entry_price = price * (1+SLIPPAGE)*(1+FEE)
                    entry_equity = equity[-1]; entry_regime = "trend" if bool(row["is_trend"]) else "mr"
                    trail_stop = price - atr_val * ATR_TRAIL_MULT; hard_stop = price - atr_val * MR_ATR_STOP_MULT
                else:
                    pos_side = -1; entry_price = price * (1-SLIPPAGE)*(1-FEE)
                    entry_equity = equity[-1]; entry_regime = "trend" if bool(row["is_trend"]) else "mr"
                    trail_stop = price + atr_val * ATR_TRAIL_MULT; hard_stop = price + atr_val * MR_ATR_STOP_MULT

                trades.append({"entry_time": df.index[i], "entry_price": entry_price, "side": "LONG" if pos_side==1 else "SHORT", "regime": entry_regime, "exit_reason": None, "exit_price": None, "return": None})
                equity.append(equity[-1]); continue

        # ── 跟踪止损 ──
        if pos_side == 1: trail_stop = max(trail_stop, price - atr_val * ATR_TRAIL_MULT)
        elif pos_side == -1: trail_stop = min(trail_stop, price + atr_val * ATR_TRAIL_MULT)

        # ── MTM + Funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i-1]["close"])
            pnl = contracts * (price - prev_price) if pos_side == 1 else contracts * (prev_price - price)
            new_eq = equity[-1] + pnl - (contracts * price) * FUNDING_RATE
            equity.append(new_eq); peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak if peak > 0 else 0)
        else:
            equity.append(equity[-1])

    # 最终平仓
    if pos_side != 0:
        last_px = float(df.iloc[-1]["close"])
        pnl = (last_px * (1-SLIPPAGE)*(1-FEE) - entry_price) * contracts if pos_side == 1 else (entry_price - last_px * (1+SLIPPAGE)*(1+FEE)) * contracts
        ret = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"; trades[-1]["exit_price"] = last_px; trades[-1]["return"] = ret; trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    equity_s = pd.Series(equity[:len(df)], index=df.index)
    completed = [t for t in trades if t["return"] is not None]
    n = len(completed)
    rets = [t["return"] for t in completed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    total_ret = float(equity_s.iloc[-1] / INITIAL - 1) * 100
    n_years = (equity_s.index[-1] - equity_s.index[0]).days / 365.25
    ann_ret = ((1+total_ret/100)**(1/n_years)-1)*100 if n_years > 0 and total_ret > -100 else 0
    peak_s = equity_s.expanding().max()
    dd_s = (peak_s - equity_s) / peak_s
    max_dd = float(dd_s.max()) * 100
    daily = equity_s.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(365.25)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    benchmark = df["close"] / df["close"].iloc[0]
    liqs = sum(1 for t in completed if "liquid" in str(t.get("exit_reason", "")))
    n_held = len([t for t in completed if t.get("exit_reason") != "liquid" and t["return"] is not None])

    return {
        "total_return": round(total_ret, 2), "annual_return": round(ann_ret, 2),
        "max_drawdown": round(max_dd, 2), "sharpe_ratio": round(sharpe, 3),
        "num_trades": n, "win_rate": round(len(wins)/n*100, 1) if n else 0,
        "profit_factor": round(abs(sum(wins)/sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "liquidations": liqs, "benchmark_return": round((benchmark.iloc[-1]-1)*100, 2),
        "long_trades": len([t for t in completed if t["side"] == "LONG"]),
        "short_trades": len([t for t in completed if t["side"] == "SHORT"]),
    }


if __name__ == "__main__":
    print("=" * 70)
    print("  1h 专属策略 v1 — 快速ADX7 + 量价一致 + 紧止损")
    print("=" * 70)

    df = load_data()
    if df.index.tz is not None: df.index = df.index.tz_localize(None)
    orig_len = len(df)
    df = df.iloc[ADX_PERIOD * 3:]  # 跳过预热
    # slice to 2023-2026 for forward test OR 2019-2026 full
    df_forward = df[(df.index >= "2025-06-01") & (df.index < "2026-05-25")].copy()
    df_full = df[(df.index >= "2023-01-01")].copy()  # 1h 全量数据起点

    for label, d in [("2023-2026 周期", df_full), ("2025-06 前测", df_forward)]:
        d = compute_signals(d)
        r = run_backtest(d)
        if "error" in r:
            print(f"  {label}: ERROR")
            continue
        final = INITIAL * (1 + r["total_return"] / 100)
        print(f"\n  {label}:")
        print(f"    ${final:,.0f}  Ret {r['total_return']:+.1f}%  Ann {r['annual_return']:+.1f}%")
        print(f"    Sharpe {r['sharpe_ratio']:.3f}  DD {r['max_drawdown']:.1f}%  "
              f"Trades {r['num_trades']} (L:{r['long_trades']} S:{r['short_trades']})  "
              f"Win {r['win_rate']}%  PF {r['profit_factor']}  Liq {r['liquidations']}")

    print()
    print("  4h 基线对比 (vol_corr>0):")
    print("    2023-2026: Final $44,083  Sharpe 1.414  DD 24.7%")
    print("    2025前测:   Final $14,407  Sharpe 1.714  DD 22.8%")
    print()

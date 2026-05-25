"""手动跟单 — 检查当前是否有新信号，给出操作指令。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals
import backtests.adx_adaptive_perp_eth_4h as strat_mod

# ── 参数 ──
SYMBOL = "ETH/USDT"
TIMEFRAME = "4h"
LEVERAGE = 10
CAPITAL = 100        # 当前权益
RISK_PER_TRADE = 0.04  # 4%

strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 2.5
strat_mod.MR_ATR_STOP_MULT = 3.5
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

# ── 加载最新数据 ──
df = load_data(ROOT / "data" / "eth_usdt_4h.csv")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

# 计算信号
df = compute_signals(df)

# 量价一致过滤
corr = df["close"].rolling(20).corr(df["volume"])
df.loc[corr.fillna(0) <= 0, "long_sig"] = False
df.loc[corr.fillna(0) <= 0, "short_sig"] = False

# ── 最近 3 根 K 线 ──
recent = df.iloc[-3:].copy()
current = df.iloc[-1]
last_price = float(current["close"])
atr = float(current.get("atr", 0) or 0) or last_price * 0.02

print("=" * 55)
print(f"  ETH/USDT 4h 手动跟单信号")
print(f"  {current.name}")
print("=" * 55)
print(f"  当前价格: ${last_price:,.2f}")
print(f"  ATR: ${atr:.2f} ({atr/last_price*100:.2f}%)")
print(f"  ADX: {current['adx']:.1f}")
state = "趋势" if current['adx'] > 30 else "震荡" if current['adx'] < 15 else "过渡"
print(f"  市场状态: {state}")
print()

# ── 检查是否有新信号 ──
new_long = bool(recent.iloc[-1]["long_sig"]) and not any(recent.iloc[:-1]["long_sig"])
new_short = bool(recent.iloc[-1]["short_sig"]) and not any(recent.iloc[:-1]["short_sig"])
in_long = bool(current.get("close_sig", False)) or bool(current.get("close_trend", False))
in_short = bool(current.get("cover_sig", False)) or bool(current.get("cover_trend", False))

# 持仓状态（简易：最后3根是否有入场信号且未被平仓）
signal_cols = ["long_sig", "short_sig", "close_sig", "cover_sig", "close_trend", "cover_trend"]

if new_long:
    stop = last_price - atr * strat_mod.ATR_TRAIL_MULT
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((last_price - stop) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做多!")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({-(last_price-stop)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    print(f"    操作: Binance 合约 → 开多 {pos_size:.4f} ETH → 设止损 ${stop:.2f}")
elif new_short:
    stop = last_price + atr * strat_mod.ATR_TRAIL_MULT
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((stop - last_price) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做空!")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({(stop-last_price)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    print(f"    操作: Binance 合约 → 开空 {pos_size:.4f} ETH → 设止损 ${stop:.2f}")
else:
    # 检查是否持仓中
    last_long = (df["long_sig"] & ~df["close_sig"] & ~df["close_trend"]).iloc[-20:].any()
    last_short = (df["short_sig"] & ~df["cover_sig"] & ~df["cover_trend"]).iloc[-20:].any()
    if last_long:
        trail = last_price - atr * strat_mod.ATR_TRAIL_MULT
        print(f"  [持仓] 做多中")
        print(f"    跟踪止损: ${trail:.2f}")
        print(f"    操作: 检查止损是否触发，未触发则继续持有")
    elif last_short:
        trail = last_price + atr * strat_mod.ATR_TRAIL_MULT
        print(f"  [持仓] 做空中")
        print(f"    跟踪止损: ${trail:.2f}")
        print(f"    操作: 检查止损是否触发，未触发则继续持有")
    else:
        print(f"  [空仓] 无信号，等待")
        print(f"    下次检查: {pd.Timestamp(current.name) + pd.Timedelta(hours=4)}")
print()
print(f"  ETH 24h: {((df['close'].iloc[-1] / df['close'].iloc[-7] - 1) * 100):+.1f}%")
print(f"  ETH 周变化: {((df['close'].iloc[-1] / df['close'].iloc[-43] - 1) * 100):+.1f}%")

# 输出简洁版给 Telegram
print("---TELEGRAM---")
if new_long:
    print(f"做多信号! 价格 ${last_price:.0f} 止损 ${(last_price-atr*strat_mod.ATR_TRAIL_MULT):.0f}")
elif new_short:
    print(f"做空信号! 价格 ${last_price:.0f} 止损 ${(last_price+atr*strat_mod.ATR_TRAIL_MULT):.0f}")
elif last_long:
    print(f"做多持仓中 当前 ${last_price:.0f}")
elif last_short:
    print(f"做空持仓中 当前 ${last_price:.0f}")
else:
    print(f"空仓 ADX={current['adx']:.0f}")
print()

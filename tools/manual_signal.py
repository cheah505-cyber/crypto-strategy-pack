"""手动跟单 — 2-regime Donchian breakout, 10% risk, 10x leverage."""
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

# ── 参数 (synced with strategy baseline 2026-05-30) ──
SYMBOL = "ETH/USDT"
TIMEFRAME = "4h"
LEVERAGE = 10
CAPITAL = 100            # 当前权益
RISK_PER_TRADE = 0.10    # 10%

strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ATR_TRAIL_MULT = 2.5
strat_mod.TRAN_ATR_TRAIL_MULT = 0.8
strat_mod.RISK_PER_TRADE = 0.10
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

# ── 加载最新数据 ──
df = load_data(ROOT / "data" / "eth_usdt_4h.csv")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

# 计算信号
df = compute_signals(df)

# ── 最近 3 根 K 线 ──
recent = df.iloc[-3:].copy()
current = df.iloc[-1]
last_price = float(current["close"])
atr = float(current.get("atr", 0) or 0) or last_price * 0.02

# 确定 regime 和对应止损乘数
is_trend = bool(current["is_trend"])
is_trans = bool(current["is_transition"])
regime = "趋势" if is_trend else "过渡"
atr_mult = strat_mod.ATR_TRAIL_MULT if is_trend else strat_mod.TRAN_ATR_TRAIL_MULT

print("=" * 55)
print(f"  ETH/USDT 4h 手动跟单信号 (2-regime)")
print(f"  {current.name}")
print("=" * 55)
print(f"  当前价格: ${last_price:,.2f}")
print(f"  ATR: ${atr:.2f} ({atr/last_price*100:.2f}%)")
print(f"  ADX: {current['adx']:.1f}")
sma100 = float(current.get("sma100", 0) or 0)
short_ok = "允许" if last_price <= sma100 else "禁止(SMA100)"
print(f"  市场状态: {regime} (止损 {atr_mult}x ATR) | SMA100: ${sma100:.0f} | 做空: {short_ok}")
print()

# ── 检查是否有新信号 ──
new_long = bool(recent.iloc[-1]["long_sig"]) and not any(recent.iloc[:-1]["long_sig"])
new_short = bool(recent.iloc[-1]["short_sig"]) and not any(recent.iloc[:-1]["short_sig"])
close_long = bool(current.get("close_trend", False))
close_short = bool(current.get("cover_trend", False))

if new_long:
    stop = last_price - atr * atr_mult
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((last_price - stop) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做多! ({regime}模式)")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({-(last_price-stop)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    print(f"    操作: Binance 合约 → 开多 {pos_size:.4f} ETH → 设止损 ${stop:.2f}")
elif new_short:
    stop = last_price + atr * atr_mult
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((stop - last_price) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做空! ({regime}模式)")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({(stop-last_price)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    print(f"    操作: Binance 合约 → 开空 {pos_size:.4f} ETH → 设止损 ${stop:.2f}")
else:
    has_close_signal = close_long or close_short
    last_long = (df["long_sig"] & ~df["close_trend"]).iloc[-20:].any()
    last_short = (df["short_sig"] & ~df["cover_trend"]).iloc[-20:].any()
    if has_close_signal:
        print(f"  [信号] 平仓!")
        if close_long:
            print(f"    平多做空信号")
        if close_short:
            print(f"    平空做多信号")
        print(f"    当前价: ${last_price:.2f}")
        print(f"    操作: Binance 合约 → 平仓")
    elif last_long:
        trail = last_price - atr * atr_mult
        print(f"  [持仓] 做多中 ({regime})")
        print(f"    跟踪止损: ${trail:.2f}")
        print(f"    操作: 检查止损是否触发，未触发则继续持有")
    elif last_short:
        trail = last_price + atr * atr_mult
        print(f"  [持仓] 做空中 ({regime})")
        print(f"    跟踪止损: ${trail:.2f}")
        print(f"    操作: 检查止损是否触发，未触发则继续持有")
    else:
        print(f"  [空仓] 无信号，等待")
        print(f"    下次检查: {pd.Timestamp(current.name) + pd.Timedelta(hours=4)}")
print()
print(f"  ETH 24h: {((df['close'].iloc[-1] / df['close'].iloc[-7] - 1) * 100):+.1f}%")
print(f"  ETH 周变化: {((df['close'].iloc[-1] / df['close'].iloc[-43] - 1) * 100):+.1f}%")

# ── 详细输出给 Telegram ──
print("---TELEGRAM---")
ts = str(current.name)[:16]
chg_24h = (df['close'].iloc[-1] / df['close'].iloc[-7] - 1) * 100
chg_wk = (df['close'].iloc[-1] / df['close'].iloc[-43] - 1) * 100
print(f"📊 ETH 4h 信号 | {ts}")
print(f"价格: ${last_price:.0f} | ADX: {current['adx']:.0f} | {regime}")
print(f"SMA100: ${sma100:.0f} | 24h: {chg_24h:+.1f}% | 周: {chg_wk:+.1f}%")
if close_long:
    print(f"🔔 平多信号! 离场 @ ${last_price:.0f}")
elif close_short:
    print(f"🔔 平空信号! 离场 @ ${last_price:.0f}")
elif new_long:
    stop = last_price - atr * atr_mult
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((last_price - stop) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"🟢 做多信号 ({regime})")
    print(f"入场: ${last_price:.0f} | 止损: ${stop:.0f} ({(stop/last_price-1)*100:+.1f}%)")
    print(f"仓位: {pos_size:.4f} ETH | 名义: ${notional:.0f} | 保证金: ${margin:.1f}")
elif new_short:
    stop = last_price + atr * atr_mult
    risk_usd = CAPITAL * RISK_PER_TRADE
    pos_size = min(risk_usd / ((stop - last_price) / last_price), CAPITAL * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"🔴 做空信号 ({regime})")
    print(f"入场: ${last_price:.0f} | 止损: ${stop:.0f} ({(stop/last_price-1)*100:+.1f}%)")
    print(f"仓位: {pos_size:.4f} ETH | 名义: ${notional:.0f} | 保证金: ${margin:.1f}")
elif last_long:
    trail = last_price - atr * atr_mult
    print(f"🟢 做多持仓中 | 入场信号已触发")
    print(f"当前价: ${last_price:.0f} | 移动止损: ${trail:.0f}")
elif last_short:
    trail = last_price + atr * atr_mult
    print(f"🔴 做空持仓中 | 入场信号已触发")
    print(f"当前价: ${last_price:.0f} | 移动止损: ${trail:.0f}")
else:
    print(f"⚪ 空仓等待 | 下次检查: {pd.Timestamp(current.name) + pd.Timedelta(hours=4)}")
print()

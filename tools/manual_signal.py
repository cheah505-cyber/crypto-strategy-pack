"""手动跟单 — 2-regime Donchian breakout, 10% risk, 10x leverage.

Reads paper_trade state as single source of truth for position tracking.
Signal logic (strategy) is read-only — never modified here.
"""
from __future__ import annotations

import json
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

# 计算信号 (strategy code — read-only)
df = compute_signals(df)

# ── 加载纸面交易状态 (单一真相源) ──
STATE_FILE = ROOT / "paper_trade" / "state.json"
pt_pos = 0
pt_entry_price = 0.0
pt_trail_stop = 0.0
pt_entry_time = None
pt_equity = CAPITAL
if STATE_FILE.exists():
    pt = json.loads(STATE_FILE.read_text())
    pt_pos = pt.get("pos_side", 0)
    pt_entry_price = pt.get("entry_price", 0.0)
    pt_trail_stop = pt.get("trail_stop", 0.0)
    pt_entry_time = pt.get("entry_time")
    pt_equity = pt.get("equity", CAPITAL)

# ── 最近 3 根 K 线 ──
recent = df.iloc[-3:].copy()
current = df.iloc[-1]
last_price = float(current["close"])
atr = float(current.get("atr", 0) or 0) or last_price * 0.02
bar_time = str(current.name)[:16]

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

# ── 冷却检查 ──
consec_losses = pt.get("consec_losses", 0) if STATE_FILE.exists() else 0
cooldown_until = pt.get("cooldown_until", -1) if STATE_FILE.exists() else -1
bar_num = len(df) - 1
in_cooldown = bar_num < cooldown_until

# ── 检查是否有新信号 ──
new_long = bool(recent.iloc[-1]["long_sig"]) and not any(recent.iloc[:-1]["long_sig"])
new_short = bool(recent.iloc[-1]["short_sig"]) and not any(recent.iloc[:-1]["short_sig"])
close_long = bool(current.get("close_trend", False))
close_short = bool(current.get("cover_trend", False))

if new_long:
    stop = last_price - atr * atr_mult
    risk_usd = pt_equity * RISK_PER_TRADE
    pos_size = min(risk_usd / ((last_price - stop) / last_price), pt_equity * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做多! ({regime}模式)")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({-(last_price-stop)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    if pt_pos != 0:
        print(f"  ⚠ paper_trade已有持仓({pt_pos}), 请手动确认是否加仓")
elif new_short:
    stop = last_price + atr * atr_mult
    risk_usd = pt_equity * RISK_PER_TRADE
    pos_size = min(risk_usd / ((stop - last_price) / last_price), pt_equity * LEVERAGE) / last_price
    notional = pos_size * last_price
    margin = notional / LEVERAGE
    print(f"  [信号] 做空! ({regime}模式)")
    print(f"    入场: 市价 ~${last_price:.2f}")
    print(f"    止损: ${stop:.2f} ({(stop-last_price)/last_price*100:.1f}%)")
    print(f"    开仓: {pos_size:.4f} ETH (名义 ${notional:.0f}, 保证金 ${margin:.1f})")
    if pt_pos != 0:
        print(f"  ⚠ paper_trade已有持仓({pt_pos}), 请手动确认是否加仓")
elif pt_pos != 0:
    # ── paper_trade 有持仓 → 以 paper_trade 为准 ──
    side_cn = "多" if pt_pos == 1 else "空"
    pnl_pct = (last_price - pt_entry_price) / pt_entry_price * 100
    if pt_pos == -1:
        pnl_pct = -pnl_pct
    trail_dist = abs(last_price - pt_trail_stop)
    trail_pct = trail_dist / last_price * 100
    stop_triggered = (pt_pos == 1 and last_price <= pt_trail_stop) or (pt_pos == -1 and last_price >= pt_trail_stop)
    print(f"  [paper_trade持仓] 做{side_cn}中 (自 {pt_entry_time})")
    print(f"    入场价: ${pt_entry_price:.2f} | 现价: ${last_price:.2f} ({pnl_pct:+.1f}%)")
    print(f"    跟踪止损: ${pt_trail_stop:.2f} (距离 {trail_pct:.1f}%)")
    if stop_triggered:
        print(f"  ⚠ 当前价已触止损! paper_trade下次运行将平仓")
    else:
        print(f"    操作: 持有，止损未触发")
    # Check for close signal as additional warning
    if (pt_pos == 1 and bool(current.get("close_trend", False))) or \
       (pt_pos == -1 and bool(current.get("cover_trend", False))):
        print(f"  ⚠ 策略平仓信号已触发, paper_trade下次运行将平仓")
else:
    # ── paper_trade 空仓 + 无新信号 ──
    print(f"  [空仓] 无信号 (paper_trade确认)")
    if not in_cooldown:
        print(f"    下次检查: {pd.Timestamp(current.name) + pd.Timedelta(hours=4)}")
    else:
        print(f"    冷却中，跳过入场检查")
print()
print(f"  ETH 24h: {((df['close'].iloc[-1] / df['close'].iloc[-7] - 1) * 100):+.1f}%")
print(f"  ETH 周变化: {((df['close'].iloc[-1] / df['close'].iloc[-43] - 1) * 100):+.1f}%")

# ── 详细输出给 Telegram ──
print("---TELEGRAM---")
chg_24h = (df['close'].iloc[-1] / df['close'].iloc[-7] - 1) * 100
chg_wk = (df['close'].iloc[-1] / df['close'].iloc[-43] - 1) * 100
print(f"📊 ETH 4h 信号 | {bar_time}")
print(f"价格: ${last_price:.0f} | ADX: {current['adx']:.0f} | {regime}")
print(f"SMA100: ${sma100:.0f} | 24h: {chg_24h:+.1f}% | 周: {chg_wk:+.1f}%")
if pt_pos != 0:
    # paper_trade has position → report actual position state
    side_emoji = "🟢" if pt_pos == 1 else "🔴"
    side_cn = "多" if pt_pos == 1 else "空"
    pnl_pct = (last_price - pt_entry_price) / pt_entry_price * 100
    if pt_pos == -1:
        pnl_pct = -pnl_pct
    stop_triggered = (pt_pos == 1 and last_price <= pt_trail_stop) or (pt_pos == -1 and last_price >= pt_trail_stop)
    print(f"{side_emoji} 做{side_cn}持仓中 | 入场${pt_entry_price:.0f} | PnL {pnl_pct:+.1f}%")
    print(f"止损: ${pt_trail_stop:.0f} {'⚠已触发!' if stop_triggered else '✓安全'}")
elif new_long:
    stop = last_price - atr * atr_mult
    risk_usd = pt_equity * RISK_PER_TRADE
    pos_size = min(risk_usd / ((last_price - stop) / last_price), pt_equity * LEVERAGE) / last_price
    notional = pos_size * last_price
    print(f"🟢 做多信号 ({regime})")
    print(f"入场: ${last_price:.0f} | 止损: ${stop:.0f} ({(stop/last_price-1)*100:+.1f}%)")
    print(f"仓位: {pos_size:.4f} ETH | 名义${notional:.0f}")
elif new_short:
    stop = last_price + atr * atr_mult
    risk_usd = pt_equity * RISK_PER_TRADE
    pos_size = min(risk_usd / ((stop - last_price) / last_price), pt_equity * LEVERAGE) / last_price
    notional = pos_size * last_price
    print(f"🔴 做空信号 ({regime})")
    print(f"入场: ${last_price:.0f} | 止损: ${stop:.0f} ({(stop/last_price-1)*100:+.1f}%)")
    print(f"仓位: {pos_size:.4f} ETH | 名义${notional:.0f}")
elif close_long or close_short:
    print(f"🔔 平仓信号! 离场 @ ${last_price:.0f}")
else:
    next_check = pd.Timestamp(current.name) + pd.Timedelta(hours=4)
    cooldown_str = " 冷却中" if in_cooldown else ""
    print(f"⚪ 空仓等待{cooldown_str} | 下次检查: {str(next_check)[:16]}")
if consec_losses >= 4:
    print(f"⚠ 连败{consec_losses}笔 | 权益${pt_equity:.2f}")
print()

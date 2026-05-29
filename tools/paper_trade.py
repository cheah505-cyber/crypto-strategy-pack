"""Paper trading tracker — real data, real signals, zero real money.

Records every trade, equity curve, and daily status.
Commits results to git for immutable public record.
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals
import backtests.adx_adaptive_perp_eth_4h as s
import constants as C

# ── Config ──
INITIAL_CAPITAL = 100.0       # $100 paper account
LEVERAGE = 10
RISK_PER_TRADE = 0.10
LOG_FILE = ROOT / "paper_trade" / "trades.csv"
STATE_FILE = ROOT / "paper_trade" / "state.json"
EQUITY_FILE = ROOT / "paper_trade" / "equity.csv"

s.FEE = C.FEE_TAKER
s.SLIPPAGE = C.SLIPPAGE_ETH
s.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
s.ADX_TREND = 30
s.ATR_TRAIL_MULT = 2.5
s.TRAN_ATR_TRAIL_MULT = 0.8
s.RISK_PER_TRADE = RISK_PER_TRADE
s.MAX_LEVERAGE = LEVERAGE

# ── Load data ──
df = load_data(ROOT / "data" / "eth_usdt_4h.csv")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

df = compute_signals(df)

# ── Load or init state ──
import json

if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text())
    equity = state["equity"]
    peak = state.get("peak", equity)
    max_dd = state.get("max_dd", 0.0)
    pos_side = state.get("pos_side", 0)
    entry_price = state.get("entry_price", 0.0)
    entry_equity = state.get("entry_equity", equity)
    entry_time = state.get("entry_time")
    entry_regime = state.get("entry_regime", "")
    entry_contracts = state.get("entry_contracts", 0.0)
    trail_stop = state.get("trail_stop", 0.0)
    consec_losses = state.get("consec_losses", 0)
    cooldown_until = state.get("cooldown_until", 0)
    trade_count = state.get("trade_count", 0)
    last_processed = state.get("last_processed")
else:
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    pos_side = 0
    entry_price = 0.0
    entry_equity = INITIAL_CAPITAL
    entry_time = None
    entry_regime = ""
    trail_stop = 0.0
    entry_contracts = 0.0
    consec_losses = 0
    cooldown_until = -1
    trade_count = 0
    last_processed = None
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Process new bars since last run ──
if last_processed:
    new_bars = df[df.index > last_processed]
else:
    new_bars = df  # first run: process full history to sync position state

recorded_trades = []
if LOG_FILE.exists():
    recorded_trades = pd.read_csv(LOG_FILE).to_dict("records")

equity_history = []
if EQUITY_FILE.exists():
    equity_history = pd.read_csv(EQUITY_FILE).to_dict("records")

for i in range(len(new_bars)):
    bar_idx = new_bars.index[i]
    row = df.loc[bar_idx]
    price = float(row["close"])
    atr_val = float(row.get("atr", 0) or 0) or price * 0.02
    bar_num = df.index.get_loc(bar_idx)
    in_cooldown = bar_num < cooldown_until

    # ── Liquidation check ──
    if pos_side != 0:
        margin = (entry_contracts * price) / LEVERAGE
        if equity <= 0 or (margin > 0 and equity < margin * 0.1):
            if pos_side == 1:
                pnl = (s.exit_value(price) - entry_price) * entry_contracts
            else:
                pnl = (entry_price - s.entry_cost(price)) * entry_contracts
            ret = pnl / entry_equity if entry_equity > 0 else 0
            trade_count += 1
            recorded_trades.append({
                "trade_id": trade_count,
                "entry_time": str(entry_time),
                "exit_time": str(bar_idx),
                "side": "LONG" if pos_side == 1 else "SHORT",
                "regime": entry_regime,
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "return_pct": round(ret * 100, 2),
                "exit_reason": "liquidated",
            })
            equity = max(entry_equity + pnl, 0.01)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0)
            consec_losses = consec_losses + 1 if ret <= 0 else 0
            if consec_losses >= 5:
                cooldown_until = bar_num + 24
            pos_side = 0
            continue

    # ── Exit check ──
    if pos_side != 0:
        close_trend = bool(row.get("close_trend", False))
        cover_trend = bool(row.get("cover_trend", False))
        stop_hit = False
        reason = ""

        if pos_side == 1:
            if price < trail_stop:
                stop_hit = True; reason = "trail_stop"
            elif close_trend:
                stop_hit = True; reason = "signal"
        else:
            if price > trail_stop:
                stop_hit = True; reason = "trail_stop"
            elif cover_trend:
                stop_hit = True; reason = "signal"

        if stop_hit:
            if pos_side == 1:
                pnl = (s.exit_value(price) - entry_price) * entry_contracts
            else:
                pnl = (entry_price - s.entry_cost(price)) * entry_contracts
            ret = pnl / entry_equity if entry_equity > 0 else 0
            trade_count += 1
            recorded_trades.append({
                "trade_id": trade_count,
                "entry_time": str(entry_time),
                "exit_time": str(bar_idx),
                "side": "LONG" if pos_side == 1 else "SHORT",
                "regime": entry_regime,
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "return_pct": round(ret * 100, 2),
                "exit_reason": reason,
            })
            equity = max(entry_equity + pnl, 0.01)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0)
            consec_losses = consec_losses + 1 if ret <= 0 else 0
            if consec_losses >= 5:
                cooldown_until = bar_num + 24
            pos_side = 0
            continue

    # ── Entry check ──
    if pos_side == 0 and not in_cooldown:
        enter_long = bool(row["long_sig"])
        enter_short = bool(row["short_sig"])
        if enter_long or enter_short:
            if bool(row["is_trend"]):
                entry_regime = "trend"
                tmult = s.ATR_TRAIL_MULT
            else:
                entry_regime = "transition"
                tmult = s.TRAN_ATR_TRAIL_MULT

            entry_contracts = s.calc_contracts(equity, price, atr_val, LEVERAGE)
            if enter_long:
                pos_side = 1
                entry_price = s.entry_cost(price)
                entry_equity = equity
                entry_time = str(bar_idx)
                trail_stop = price - atr_val * tmult
            else:
                pos_side = -1
                entry_price = s.exit_value(price)
                entry_equity = equity
                entry_time = str(bar_idx)
                trail_stop = price + atr_val * tmult
            continue

    # ── Trail stop update ──
    if pos_side == 1:
        trail_stop = max(trail_stop, price - atr_val * (s.ATR_TRAIL_MULT if entry_regime == "trend" else s.TRAN_ATR_TRAIL_MULT))
    elif pos_side == -1:
        trail_stop = min(trail_stop, price + atr_val * (s.ATR_TRAIL_MULT if entry_regime == "trend" else s.TRAN_ATR_TRAIL_MULT))

    # ── MTM + Funding ──
    if pos_side != 0 and i > 0:
        prev_price = float(new_bars.iloc[i - 1]["close"])
        if pos_side == 1:
            mtm = entry_contracts * (price - prev_price)
        else:
            mtm = entry_contracts * (prev_price - price)
        funding = (entry_contracts * price) * s.FUNDING_RATE
        equity = equity + mtm - funding
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0)

    # Record equity
    equity_history.append({
        "timestamp": str(bar_idx),
        "equity": round(equity, 4),
        "position": pos_side,
    })

# ── Save state ──
STATE_FILE.write_text(json.dumps({
    "equity": equity,
    "peak": peak,
    "max_dd": max_dd,
    "pos_side": pos_side,
    "entry_price": entry_price,
    "entry_equity": entry_equity,
    "entry_time": entry_time,
    "entry_regime": entry_regime,
    "entry_contracts": entry_contracts,
    "trail_stop": trail_stop,
    "consec_losses": consec_losses,
    "cooldown_until": cooldown_until,
    "trade_count": trade_count,
    "last_processed": str(new_bars.index[-1]) if len(new_bars) > 0 else last_processed,
}, indent=2))

# ── Save trade log ──
if recorded_trades:
    pd.DataFrame(recorded_trades).to_csv(LOG_FILE, index=False)

# ── Save equity history ──
if equity_history:
    pd.DataFrame(equity_history).to_csv(EQUITY_FILE, index=False)

# ── Print status ──
current = df.iloc[-1]
last_price = float(current["close"])
regime = "趋势" if bool(current["is_trend"]) else "过渡"
atr_mult = s.ATR_TRAIL_MULT if bool(current["is_trend"]) else s.TRAN_ATR_TRAIL_MULT
sma100 = float(current.get("sma100", 0) or 0)
short_ok = "允许" if last_price <= sma100 else "禁止"

print("=" * 55)
print(f"  PAPER TRADING — ${equity:.2f} (start: ${INITIAL_CAPITAL:.0f})")
print(f"  {str(new_bars.index[-1]) if len(new_bars) > 0 else df.index[-1]}")
print("=" * 55)
print(f"  Price:     ${last_price:,.2f}")
print(f"  ADX:       {current['adx']:.1f}  |  Regime: {regime} ({atr_mult}x ATR)")
print(f"  SMA100:    ${sma100:,.0f}  |  Shorts: {short_ok}")
print(f"  Return:    {((equity-INITIAL_CAPITAL)/INITIAL_CAPITAL*100):+.1f}%")
print(f"  Max DD:    {max_dd*100:.1f}%")
print(f"  Trades:    {trade_count}")
print()

if pos_side == 1:
    tmult = s.ATR_TRAIL_MULT if entry_regime == "trend" else s.TRAN_ATR_TRAIL_MULT
    print(f"  [POSITION] LONG ({entry_regime})")
    print(f"    Entry:   ${entry_price:.2f}")
    print(f"    Stop:    ${trail_stop:.2f}")
    print(f"    PnL:     {((last_price-entry_price)/entry_price*100):+.2f}% (unrealized)")
elif pos_side == -1:
    print(f"  [POSITION] SHORT ({entry_regime})")
    print(f"    Entry:   ${entry_price:.2f}")
    print(f"    Stop:    ${trail_stop:.2f}")
    print(f"    PnL:     {((entry_price-last_price)/entry_price*100):+.2f}% (unrealized)")
else:
    new_long = bool(current["long_sig"]) and not bool(df.iloc[-2]["long_sig"])
    new_short = bool(current["short_sig"]) and not bool(df.iloc[-2]["short_sig"])
    if new_long:
        print(f"  [SIGNAL] LONG — enter next bar")
    elif new_short:
        print(f"  [SIGNAL] SHORT — enter next bar")
    else:
        print(f"  [FLAT] No signal")
print()

if recorded_trades:
    last_trades = recorded_trades[-5:]
    print(f"  Last {len(last_trades)} closed trades:")
    for t in last_trades:
        side = t["side"][:1]
        print(f"    #{t['trade_id']} {side} {t['entry_time'][:10]} {t['return_pct']:>+6.1f}% {t['exit_reason']}")

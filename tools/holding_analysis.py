"""分析持仓最长时间：做多 vs 做空"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import (
    calc_contracts, compute_signals, load_data, run_backtest,
)
import backtests.adx_adaptive_perp_eth_4h as strat_mod

DATA_PATH = ROOT / "data" / "eth_usdt_4h.csv"

strat_mod.FEE = C.FEE_TAKER
strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
strat_mod.FUNDING_RATE = C.FUNDING_RATE_4H_ETH
strat_mod.ADX_TREND = 30
strat_mod.ADX_RANGE = 15
strat_mod.ATR_TRAIL_MULT = 2.5
strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE

df = load_data(DATA_PATH)
df = compute_signals(df)
r = run_backtest(df)

trades = [t for t in r["trades"] if t["return"] is not None]
for t in trades:
    entry = pd.Timestamp(t["entry_time"])
    exit_t = pd.Timestamp(t["exit_time"])
    t["holding_hours"] = (exit_t - entry).total_seconds() / 3600

longs = [t for t in trades if t["side"] == "LONG"]
shorts = [t for t in trades if t["side"] == "SHORT"]

print(f"Total trades: {len(trades)}")
print()
for label, side_trades in [("LONG", longs), ("SHORT", shorts)]:
    hours = [t["holding_hours"] for t in side_trades]
    print(f"  {label}: {len(side_trades)} trades")
    if hours:
        print(f"    Max holding:  {max(hours):.0f}h ({max(hours)/24:.1f}d)")
        print(f"    Min holding:  {min(hours):.0f}h ({min(hours)/24:.2f}d)")
        print(f"    Avg holding:  {np.mean(hours):.0f}h ({np.mean(hours)/24:.1f}d)")
        print(f"    Median:       {np.median(hours):.0f}h ({np.median(hours)/24:.1f}d)")

        # Find the longest
        longest = side_trades[hours.index(max(hours))]
        print(f"    Longest trade entry: {longest['entry_time']}")
        print(f"    Longest trade exit:  {longest['exit_time']}")
        print(f"    Longest trade return: {longest['return']*100:+.2f}%")
        print()

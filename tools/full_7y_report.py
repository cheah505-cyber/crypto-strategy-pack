"""7-year full backtest report — all details."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/Users/cheah/projects/crypto/utils')
sys.path.insert(0, 'C:/Users/cheah/projects/crypto')

from backtests import adx_adaptive_perp_eth_4h as s
import numpy as np, pandas as pd

s.MAX_LEVERAGE = 10.0
s.RISK_PER_TRADE = 0.10
s.ATR_TRAIL_MULT = 2.5
s.TRAN_ATR_TRAIL_MULT = 0.8

# Load full 7-year data
df = pd.read_csv("C:/Users/cheah/projects/crypto/data/eth_usdt_4h_full.csv",
                 parse_dates=["timestamp"], index_col="timestamp")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

years = (df.index[-1] - df.index[0]).days / 365.25
print(f"Data: {df.index.min().date()} -> {df.index.max().date()} ({len(df)} bars, {years:.1f} years)")

df = s.compute_signals(df)
r = s.run_backtest(df)

INITIAL = 10000
final = INITIAL * (1 + r["total_return"] / 100)

print(f"\n{'='*65}")
print(f"  7-Year Full Backtest — 10% Risk, 10x Lev, Binance Perps")
print(f"{'='*65}")
print(f"")
print(f"  Period:         {df.index.min().date()} -> {df.index.max().date()} ({years:.1f} years)")
print(f"  Bars:           {len(df):,}")
print(f"  Initial:        ${INITIAL:,.0f}")
print(f"  Final:          ${final:,.0f}")
print(f"  Total Return:   {r['total_return']:+.1f}%")
print(f"  Annual Return:  {r['annual_return']:+.1f}%")
print(f"  Max Drawdown:   {r['max_drawdown']:.1f}%")
print(f"  Sharpe Ratio:   {r['sharpe_ratio']:.3f}")
print(f"  Calmar Ratio:   {r['calmar_ratio']:.3f}")
print(f"  Ann Volatility: {r['ann_volatility']:.1f}%")

# Trade stats
trades = r["trades"]
longs = [t for t in trades if t["side"] == "LONG"]
shorts = [t for t in trades if t["side"] == "SHORT"]
trend_t = [t for t in trades if t["regime"] == "trend"]
trans_t = [t for t in trades if t["regime"] == "transition"]

l_pnl = sum(t["return"] * 100 for t in longs)
s_pnl = sum(t["return"] * 100 for t in shorts)
t_pnl = sum(t["return"] * 100 for t in trend_t)
x_pnl = sum(t["return"] * 100 for t in trans_t)

print(f"")
print(f"  Trades:         {len(trades)} (L:{len(longs)} S:{len(shorts)} | Trend:{len(trend_t)} Trans:{len(trans_t)})")
print(f"  Win Rate:       {r['win_rate']}%")
print(f"  Profit Factor:  {r['profit_factor']}")
print(f"  Avg Trade:      {r['avg_return']:+.2f}%")
print(f"  Avg Win:        {r['avg_win']:+.2f}%")
print(f"  Avg Loss:       {r['avg_loss']:+.2f}%")
print(f"  Liquidations:   {r['liquidations']}")
print(f"")
lw = sum(1 for t in longs if t["return"] > 0) / len(longs) * 100 if longs else 0
sw = sum(1 for t in shorts if t["return"] > 0) / len(shorts) * 100 if shorts else 0
tw = sum(1 for t in trend_t if t["return"] > 0) / len(trend_t) * 100 if trend_t else 0
xw = sum(1 for t in trans_t if t["return"] > 0) / len(trans_t) * 100 if trans_t else 0
print(f"  Long PnL:       {l_pnl:+.1f}% ({len(longs)} trades, {lw:.0f}% win)")
print(f"  Short PnL:      {s_pnl:+.1f}% ({len(shorts)} trades, {sw:.0f}% win)")
print(f"  Trend PnL:      {t_pnl:+.1f}% ({len(trend_t)} trades, {tw:.0f}% win)")
print(f"  Trans PnL:      {x_pnl:+.1f}% ({len(trans_t)} trades, {xw:.0f}% win)")

# Holding duration
durs = [(pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600 for t in trades]
print(f"")
print(f"  Holding Time:")
print(f"    Max:          {max(durs):.0f}h ({max(durs)/24:.1f} days)")
print(f"    Min:          {min(durs):.0f}h")
print(f"    Avg:          {np.mean(durs):.0f}h ({np.mean(durs)/24:.1f} days)")
print(f"    Median:       {np.median(durs):.0f}h")
dn = len(durs)
print(f"    < 1d:         {sum(1 for d in durs if d < 24)} trades ({sum(1 for d in durs if d < 24)/dn*100:.0f}%)")
print(f"    1-3d:         {sum(1 for d in durs if 24 <= d < 72)} trades ({sum(1 for d in durs if 24 <= d < 72)/dn*100:.0f}%)")
print(f"    3-7d:         {sum(1 for d in durs if 72 <= d < 168)} trades ({sum(1 for d in durs if 72 <= d < 168)/dn*100:.0f}%)")
print(f"    > 7d:         {sum(1 for d in durs if d >= 168)} trades ({sum(1 for d in durs if d >= 168)/dn*100:.0f}%)")

# Flat time
total_hours = (df.index[-1] - df.index[0]).total_seconds() / 3600
time_in_pos = sum(durs)
time_flat = total_hours - time_in_pos
print(f"")
print(f"  Position Coverage:")
print(f"    Total:        {total_hours/24:.0f} days")
print(f"    In position:  {time_in_pos/24:.0f} days ({time_in_pos/total_hours*100:.0f}%)")
print(f"    Fully flat:   {time_flat/24:.0f} days ({time_flat/total_hours*100:.0f}%)")

# Consecutive flat
flat_streaks = []
current = 0
for i in range(len(df)):
    in_trade = any(pd.Timestamp(t["entry_time"]) <= df.index[i] <= pd.Timestamp(t["exit_time"]) for t in trades)
    if not in_trade:
        current += 1
    else:
        if current > 0:
            flat_streaks.append(current * 4)
        current = 0
if current > 0:
    flat_streaks.append(current * 4)

if flat_streaks:
    print(f"    Max flat:     {max(flat_streaks):.0f}h ({max(flat_streaks)/24:.1f} days)")
    print(f"    Avg flat:     {np.mean(flat_streaks):.0f}h ({np.mean(flat_streaks)/24:.1f} days)")
    print(f"    > 7d flat:    {sum(1 for s in flat_streaks if s > 168)} times")

# Drawdown path
eq = r["equity_curve"]
peak = 1.0; max_dd_val = 0.0; trough_val = 1.0; peak_dt = None; trough_dt = None
for i, val in enumerate(eq):
    if val > peak:
        peak = val; peak_dt = eq.index[i]
    dd = (peak - val) / peak
    if dd > max_dd_val:
        max_dd_val = dd; trough_val = val; trough_dt = eq.index[i]

print(f"")
print(f"  Worst Drawdown:")
print(f"    Peak:         ${INITIAL*peak:,.0f} ({str(peak_dt)[:10]})")
print(f"    Trough:       ${INITIAL*trough_val:,.0f} ({str(trough_dt)[:10]})")
print(f"    DD:           {max_dd_val*100:.1f}%")
print(f"    DD from init: {(1-trough_val)*100:.1f}% below initial $10K")

# Recovery
trough_dt_str = str(trough_dt)
eq_after = eq[eq.index >= trough_dt]
recovered = False; rec_dt = None
for i, val in enumerate(eq_after):
    if val >= peak:
        recovered = True; rec_dt = eq_after.index[i]
        break
if recovered:
    rec_months = (rec_dt - trough_dt).days / 30
    print(f"    Recovered:    {str(rec_dt)[:10]} ({rec_months:.1f} months)")
else:
    still_dd = (peak - eq.iloc[-1]) / peak * 100
    print(f"    Recovered:    NOT YET — still {still_dd:.1f}% below peak")

# Yearly
print(f"")
print(f"  Yearly Returns:")
for year in range(2019, 2027):
    mask = df.index.year == year
    if mask.sum() == 0:
        continue
    yr_idx = df.index[df.index.year == year]
    if len(yr_idx) == 0:
        continue
    yr_eq = eq[eq.index.isin(yr_idx)]
    if len(yr_eq) < 2:
        continue
    yr_start = yr_eq.iloc[0]
    yr_end = yr_eq.iloc[-1]
    yr_ret = (yr_end - yr_start) / yr_start * 100
    bh_start = df.loc[yr_idx[0], "close"]
    bh_end = df.loc[yr_idx[-1], "close"]
    bh_ret = (bh_end - bh_start) / bh_start * 100
    yr_trades = sum(1 for t in trades if pd.Timestamp(t["entry_time"]).year == year)
    flag = " <<< BEST" if yr_ret == max([(r["total_return"]) for _ in [1]]) else ""
    print(f"    {year}:  Strat {yr_ret:>+7.1f}%  |  B&H {bh_ret:>+7.1f}%  |  {yr_trades} trades")

# Exit reasons
reasons = {}
for t in trades:
    reason = t.get("exit_reason", "unknown")
    reasons[reason] = reasons.get(reason, 0) + 1
print(f"")
print(f"  Exit Reasons:")
for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
    print(f"    {reason:<15} {count:>4} ({count/len(trades)*100:.0f}%)")

# Benchmark
print(f"")
print(f"  Benchmark:")
print(f"    B&H ETH:      {r['benchmark_return']:+.1f}%")
print(f"    Excess:        {r['excess_return']:+.1f}pp annual")
print(f"    B&H final:    ${INITIAL*(1+r['benchmark_return']/100):,.0f}")
print(f"    Strategy:     ${final:,.0f}")
print(f"    Ratio:        {final/(INITIAL*(1+r['benchmark_return']/100)):.1f}x")

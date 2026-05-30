"""Diagnose 2020-2021 underperformance."""
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

df = pd.read_csv("C:/Users/cheah/projects/crypto/data/eth_usdt_4h_full.csv",
                 parse_dates=["timestamp"], index_col="timestamp")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)

# Split periods
df20 = df[df.index.year.isin([2020, 2021])].copy()
df_bull = df[df.index.year.isin([2023, 2024, 2025])].copy()

for label, df_p in [("2020-2021 Parabolic", df20), ("2023-2025 Trend", df_bull)]:
    df_p = s.compute_signals(df_p)
    r = s.run_backtest(df_p)
    trades = r["trades"]
    longs = [t for t in trades if t["side"] == "LONG"]
    shorts = [t for t in trades if t["side"] == "SHORT"]

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Period: {df_p.index.min().date()} -> {df_p.index.max().date()}")
    print(f"  Strat: {r['total_return']:+.1f}%  |  B&H: {r['benchmark_return']:+.1f}%  |  Sharpe: {r['sharpe_ratio']:.3f}")
    print(f"  Trades: {len(trades)} (L:{len(longs)} S:{len(shorts)})  Win: {r['win_rate']}%  PF: {r['profit_factor']}")

    # Per-direction in detail
    l_ret = sum(t["return"]*100 for t in longs)
    s_ret = sum(t["return"]*100 for t in shorts)
    l_w = sum(1 for t in longs if t["return"]>0)/len(longs)*100 if longs else 0
    s_w = sum(1 for t in shorts if t["return"]>0)/len(shorts)*100 if shorts else 0
    l_avg_w = np.mean([t["return"]*100 for t in longs if t["return"]>0]) if any(t["return"]>0 for t in longs) else 0
    l_avg_l = np.mean([t["return"]*100 for t in longs if t["return"]<=0]) if any(t["return"]<=0 for t in longs) else 0
    s_avg_w = np.mean([t["return"]*100 for t in shorts if t["return"]>0]) if any(t["return"]>0 for t in shorts) else 0
    s_avg_l = np.mean([t["return"]*100 for t in shorts if t["return"]<=0]) if any(t["return"]<=0 for t in shorts) else 0

    print(f"")
    print(f"  Long:  {l_ret:+.1f}%  Win {l_w:.0f}%  AvgW {l_avg_w:+.1f}%  AvgL {l_avg_l:+.1f}%")
    print(f"  Short: {s_ret:+.1f}%  Win {s_w:.0f}%  AvgW {s_avg_w:+.1f}%  AvgL {s_avg_l:+.1f}%")

    # Regime
    trend_t = [t for t in trades if t["regime"]=="trend"]
    trans_t = [t for t in trades if t["regime"]=="transition"]
    print(f"  Trend: {len(trend_t)} trades  Trans: {len(trans_t)} trades")

    # Exit reasons
    reasons = {}
    for t in trades:
        reasons[t.get("exit_reason","?")] = reasons.get(t.get("exit_reason","?"), 0)+1
    print(f"  Exits: " + " | ".join(f"{k}:{v}" for k,v in sorted(reasons.items())))

    # Regime distribution
    trend_bars = df_p["is_trend"].sum()
    trans_bars = df_p["is_transition"].sum()
    total = len(df_p)
    print(f"  Bars: Trend {trend_bars} ({trend_bars/total*100:.0f}%) | Trans {trans_bars} ({trans_bars/total*100:.0f}%)")

# ── Deep dive: 2020 quarterly ──
print(f"\n{'='*60}")
print(f"  2020-2021 Quarterly Breakdown")
print(f"{'='*60}")
print(f"  {'Quarter':<12} {'Strat':>8} {'B&H':>8} {'Trades':>6} {'L_Win':>5} {'S_Win':>5} {'Trend%':>6}")
df_full = s.compute_signals(df)
for y in [2020, 2021]:
    for q in range(1, 5):
        mask = (df_full.index.year == y) & (df_full.index.quarter == q)
        if mask.sum() < 50: continue
        df_q = df_full[mask].copy()
        # Re-run on quarter (signals need full context, so we use pre-computed)
        # Use subset of pre-computed signals
        try:
            r_q = s.run_backtest(df_q)
            trades_q = r_q["trades"]
            lq = [t for t in trades_q if t["side"]=="LONG"]
            sq = [t for t in trades_q if t["side"]=="SHORT"]
            lw = sum(1 for t in lq if t["return"]>0)/len(lq)*100 if lq else 0
            sw = sum(1 for t in sq if t["return"]>0)/len(sq)*100 if sq else 0
            trend_pct = df_q["is_trend"].sum()/len(df_q)*100
            print(f"  {y}-Q{q:<8} {r_q['total_return']:>+7.1f}% {r_q['benchmark_return']:>+7.1f}% {r_q['num_trades']:>6} {lw:>4.0f}% {sw:>4.0f}% {trend_pct:>5.0f}%")
        except:
            print(f"  {y}-Q{q:<8} (insufficient data)")

# ── What if: skip shorts during parabolic bull? ──
print(f"\n{'='*60}")
print(f"  Counterfactual: Skip Shorts in 2020-2021")
print(f"{'='*60}")
df_fix = df_full[df_full.index.year.isin([2020,2021])].copy()
df_fix = s.compute_signals(df_fix)
r_orig = s.run_backtest(df_fix)
print(f"  Original:     Ret {r_orig['total_return']:+.1f}% Sharpe {r_orig['sharpe_ratio']:.3f} Trades {r_orig['num_trades']}")

# Kill shorts
df_fix["short_sig"] = False
r_noshort = s.run_backtest(df_fix)
print(f"  No shorts:    Ret {r_noshort['total_return']:+.1f}% Sharpe {r_noshort['sharpe_ratio']:.3f} Trades {r_noshort['num_trades']}")

# What if trend-only (kill transition longs too)?
df_fix2 = df_full[df_full.index.year.isin([2020,2021])].copy()
df_fix2 = s.compute_signals(df_fix2)
df_fix2.loc[df_fix2["is_transition"], "long_sig"] = False
df_fix2.loc[df_fix2["is_transition"], "short_sig"] = False
r_trend = s.run_backtest(df_fix2)
print(f"  Trend only:   Ret {r_trend['total_return']:+.1f}% Sharpe {r_trend['sharpe_ratio']:.3f} Trades {r_trend['num_trades']}")

# Wider stops for bull?
for trend_m, trans_m in [(3.0, 1.2), (3.5, 1.5), (4.0, 2.0)]:
    s.ATR_TRAIL_MULT = trend_m
    s.TRAN_ATR_TRAIL_MULT = trans_m
    df_t = df_full[df_full.index.year.isin([2020,2021])].copy()
    df_t = s.compute_signals(df_t)
    r_t = s.run_backtest(df_t)
    print(f"  ATR {trend_m}/{trans_m}x: Ret {r_t['total_return']:+.1f}% Sharpe {r_t['sharpe_ratio']:.3f} Trades {r_t['num_trades']}")

# Reset
s.ATR_TRAIL_MULT = 2.5
s.TRAN_ATR_TRAIL_MULT = 0.8
print(f"\n  B&H ETH 2020-2021: +{r_orig['benchmark_return']:.1f}%")

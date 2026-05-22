"""组合回测 + 执行延迟：ETH+BTC 50/50 + 1-bar delay."""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from backtests.adx_perp import (
    load_data, compute_signals, run_backtest, DATA_PATH, BTC_PATH
)
import backtests.adx_perp as mod

# ── 1. 单币延迟测试 ──
print("=" * 60)
print("1-bar Execution Delay Test")
print("=" * 60)

for name, path in [("ETH", DATA_PATH), ("BTC", BTC_PATH)]:
    df = load_data(path)
    df = compute_signals(df)
    # 延迟 1 bar: 所有信号列 shift
    df_delayed = df.copy()
    sig_cols = ["long_sig", "short_sig", "close_sig", "cover_sig",
                "close_trend", "cover_trend", "is_trend", "is_range"]
    for col in sig_cols:
        if col in df_delayed.columns:
            df_delayed[col] = df[col].shift(1).fillna(False)
    r_delayed = run_backtest(df_delayed)

    df_normal = compute_signals(df.copy())
    r_normal = run_backtest(df_normal)

    print(f"\n{name}:")
    print(f"  {'':<20} {'Normal':>10} {'+1bar Delay':>12} {'Decay':>10}")
    print(f"  {'Return %':<20} {r_normal['total_return']:>+9.1f} {r_delayed['total_return']:>+11.1f} {r_delayed['total_return']-r_normal['total_return']:>+9.1f}")
    print(f"  {'Sharpe':<20} {r_normal['sharpe_ratio']:>10.3f} {r_delayed['sharpe_ratio']:>12.3f} {r_delayed['sharpe_ratio']-r_normal['sharpe_ratio']:>+10.3f}")
    print(f"  {'Max DD %':<20} {r_normal['max_drawdown']:>+9.1f} {r_delayed['max_drawdown']:>+11.1f} {r_delayed['max_drawdown']-r_normal['max_drawdown']:>+9.1f}")
    print(f"  {'PF':<20} {r_normal['profit_factor']:>10.2f} {r_delayed['profit_factor']:>12.2f}")
    print(f"  {'Trades':<20} {r_normal['num_trades']:>10} {r_delayed['num_trades']:>12}")

# ── 2. 组合 50/50 ──
print()
print("=" * 60)
print("ETH+BTC 50/50 Portfolio")
print("=" * 60)

# Get equity curves
df_eth = load_data(DATA_PATH)
df_eth = compute_signals(df_eth)
r_eth = run_backtest(df_eth)

df_btc = load_data(BTC_PATH)
df_btc = compute_signals(df_btc)
r_btc = run_backtest(df_btc)

eq_eth = r_eth["equity_curve"]
eq_btc = r_btc["equity_curve"]

# Compute daily returns from equity, then reconstruct portfolio
eth_rets = eq_eth.pct_change().dropna()
btc_rets = eq_btc.pct_change().dropna()
common = pd.concat([eth_rets, btc_rets], axis=1, keys=["ETH", "BTC"]).dropna()
corr = float(common.corr().iloc[0, 1])

# 50/50 portfolio: average daily returns then compound
port_rets = (common["ETH"] + common["BTC"]) / 2
eq_port = (1 + port_rets).cumprod()
if len(eq_port) > 0:
    eq_port.iloc[0] = 1.0
total_ret_dec = float(eq_port.iloc[-1] - 1)
n_years = (eq_port.index[-1] - eq_port.index[0]).days / 365.25
ann_ret_dec = float((1 + total_ret_dec) ** (1/n_years) - 1) if n_years > 0 else 0
peak = eq_port.expanding().max()
dd = float(((peak - eq_port) / peak).max()) * 100
ann_vol = float(port_rets.std() * np.sqrt(365.25 * 6))
sharpe = ann_ret_dec / ann_vol if ann_vol > 0 else 0

print(f"  ETH Return:   {r_eth['total_return']:>+8.1f}%  Sharpe: {r_eth['sharpe_ratio']:.2f}  DD: {r_eth['max_drawdown']:.1f}%")
print(f"  BTC Return:   {r_btc['total_return']:>+8.1f}%  Sharpe: {r_btc['sharpe_ratio']:.2f}  DD: {r_btc['max_drawdown']:.1f}%")
print(f"  Corr(ETH,BTC): {corr:.3f}")
print(f"  ---")
print(f"  50/50 Return: {total_ret_dec*100:>+8.1f}%  Sharpe: {sharpe:.2f}  DD: {dd:.1f}%")
print(f"  Annual:       {ann_ret_dec*100:>+8.1f}%  Vol: {ann_vol*100:.1f}%")
print(f"  vs ETH alone:  Return {(total_ret_dec*100 - r_eth['total_return']):+.1f}%  Sharpe {sharpe - r_eth['sharpe_ratio']:+.2f}  DD {dd - r_eth['max_drawdown']:+.1f}%")

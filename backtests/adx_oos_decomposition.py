"""Decompose OOS Sharpe degradation into signal decay vs regime shift vs cost drag."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    load_data, compute_signals, run_backtest,
)
import backtests.adx_adaptive_perp_eth_4h as mod

TRAIN_END = "2025-07-01"


def compute_signal_quality(df: pd.DataFrame) -> dict:
    """Compute forward returns after signals to measure raw signal quality."""
    rets = df["close"].pct_change()
    metrics = {}

    for sig_name in ["long_sig", "short_sig"]:
        sig = df[sig_name].astype(bool)
        signal_bars = sig & (~sig.shift(1).fillna(False))
        if signal_bars.sum() < 5:
            metrics[sig_name] = {"count": 0, "fwd_1bar": 0, "fwd_4bar": 0, "fwd_12bar": 0}
            continue

        fwd_1 = rets.shift(-1)[signal_bars].mean()
        fwd_4 = rets.shift(-4)[signal_bars].mean()
        fwd_12 = rets.shift(-12)[signal_bars].mean()
        direction = 1 if "long" in sig_name else -1
        metrics[sig_name] = {
            "count": signal_bars.sum(),
            "fwd_1bar": round(fwd_1 * direction * 100, 4),
            "fwd_4bar": round(fwd_4 * direction * 100, 4),
            "fwd_12bar": round(fwd_12 * direction * 100, 4),
        }

    return metrics


def characterize_regime(df: pd.DataFrame) -> dict:
    """Characterize market regime: trend strength, vol, mean reversion."""
    c = df["close"]
    ret = c.pct_change().dropna()
    return {
        "total_return": round((c.iloc[-1] / c.iloc[0] - 1) * 100, 1),
        "annual_vol": round(ret.std() * np.sqrt(365.25 * 6) * 100, 1),
        "mean_daily_ret": round(ret.mean() * 100, 4),
        "autocorr_lag1": round(ret.autocorr(lag=1), 4),
        "autocorr_lag4": round(ret.autocorr(lag=4), 4),
        "max_run_up": round(((c.cummax() - c) / c.cummax()).max() * 100, 1),
        "adx_mean": round(df["adx"].mean(), 1),
        "trend_pct": round((df["adx"] > mod.ADX_TREND).mean() * 100, 1),
        "range_pct": round((df["adx"] < mod.ADX_RANGE).mean() * 100, 1),
    }


def main() -> int:
    df = load_data()
    df = compute_signals(df)

    df_train = df[df.index < TRAIN_END]
    df_test = df[df.index >= TRAIN_END]

    # 1. Signal quality comparison
    sig_train = compute_signal_quality(df_train)
    sig_test = compute_signal_quality(df_test)

    print(f"\n{'='*70}")
    print(f"  1. SIGNAL QUALITY COMPARISON")
    print(f"{'='*70}")
    print(f"{'Signal':<15} {'Train Fwd1':>10} {'Test Fwd1':>10} {'Delta':>10} "
          f"{'Train Fwd4':>10} {'Test Fwd4':>10}")
    print("-" * 60)
    for sig in ["long_sig", "short_sig"]:
        st = sig_train.get(sig, {})
        te = sig_test.get(sig, {})
        d1 = te.get("fwd_1bar", 0) - st.get("fwd_1bar", 0) if st and te else 0
        print(f"  {sig:<13} {st.get('fwd_1bar', 0):>+9.4f}% {te.get('fwd_1bar', 0):>+9.4f}% "
              f"{d1:>+9.4f}% {st.get('fwd_4bar', 0):>+9.4f}% {te.get('fwd_4bar', 0):>+9.4f}%")

    # 2. Regime comparison
    reg_train = characterize_regime(df_train)
    reg_test = characterize_regime(df_test)

    print(f"\n{'='*70}")
    print(f"  2. MARKET REGIME COMPARISON")
    print(f"{'='*70}")
    print(f"{'Metric':<25} {'Train':>12} {'Test':>12} {'Delta':>12}")
    print("-" * 62)
    for key, label in [
        ("total_return", "Period Return %"),
        ("annual_vol", "Annual Vol %"),
        ("mean_daily_ret", "Mean Daily Ret %"),
        ("autocorr_lag1", "Ret Autocorr L1"),
        ("autocorr_lag4", "Ret Autocorr L4"),
        ("adx_mean", "ADX Mean"),
        ("trend_pct", "Trend %"),
        ("range_pct", "Range %"),
    ]:
        delta = reg_test[key] - reg_train[key] if isinstance(reg_test[key], (int, float)) else 0
        print(f"  {label:<23} {str(reg_train[key]):>12} {str(reg_test[key]):>12} "
              f"{delta:>+11.1f}")

    # 3. Backtest comparison
    r_train = run_backtest(df_train.copy())
    r_test = run_backtest(df_test.copy())

    print(f"\n{'='*70}")
    print(f"  3. BACKTEST COMPARISON")
    print(f"{'='*70}")
    print(f"{'Metric':<25} {'Train':>12} {'Test':>12} {'Retention':>12}")
    print("-" * 62)
    for key, label in [
        ("sharpe_ratio", "Sharpe"),
        ("total_return", "Total Return %"),
        ("annual_return", "Annual Return %"),
        ("max_drawdown", "Max DD %"),
        ("win_rate", "Win Rate %"),
        ("profit_factor", "Profit Factor"),
        ("num_trades", "Trades"),
        ("avg_return", "Avg Return %"),
    ]:
        retention = ""
        if (isinstance(r_train.get(key), (int, float)) and isinstance(r_test.get(key), (int, float))
                and abs(r_train[key]) > 0.001):
            retention = f"{r_test[key] / r_train[key] * 100:.0f}%"
        print(f"  {label:<23} {str(r_train.get(key, 'N/A')):>12} "
              f"{str(r_test.get(key, 'N/A')):>12} {retention:>12}")

    # 4. Decomposition
    print(f"\n{'='*70}")
    print(f"  4. SHARPE DEGRADATION DECOMPOSITION")
    print(f"{'='*70}")

    train_ann = r_train.get("annual_return", 0)
    test_ann = r_test.get("annual_return", 0)
    train_sharpe = r_train.get("sharpe_ratio", 0)
    test_sharpe = r_test.get("sharpe_ratio", 0)
    train_vol = r_train.get("ann_volatility", 0)
    test_vol = r_test.get("ann_volatility", 0)

    print(f"    Sharpe: {train_sharpe:.3f} -> {test_sharpe:.3f} (delta: {test_sharpe - train_sharpe:+.3f})")
    print(f"    Return: {train_ann:+.1f}% -> {test_ann:+.1f}% (delta: {test_ann - train_ann:+.1f}%)")
    print(f"    Vol:    {train_vol:.1f}% -> {test_vol:.1f}% (delta: {test_vol - train_vol:+.1f}%)")

    long_fwd1_decay = (
        (sig_test.get("long_sig", {}).get("fwd_1bar", 0) - sig_train.get("long_sig", {}).get("fwd_1bar", 0))
        if sig_train and sig_test else 0
    )
    short_fwd1_decay = (
        (sig_test.get("short_sig", {}).get("fwd_1bar", 0) - sig_train.get("short_sig", {}).get("fwd_1bar", 0))
        if sig_train and sig_test else 0
    )

    print(f"\n    Signal decay (avg fwd 1-bar edge change):")
    print(f"      Long:  {long_fwd1_decay:+.4f}%")
    print(f"      Short: {short_fwd1_decay:+.4f}%")

    if abs(long_fwd1_decay + short_fwd1_decay) < 0.01:
        print(f"    -> Minimal signal decay. Regime shift is primary driver.")
    elif test_ann < 0 and reg_test["total_return"] > 0:
        print(f"    -> Strategy underperformed in rising market. Signal timing degraded.")
    else:
        print(f"    -> Mixed causes. See breakdown above.")

    print(f"\n    Cost drag per trade: {mod.FEE * 2 + mod.SLIPPAGE * 2:.4f} ({mod.FEE * 2 + mod.SLIPPAGE * 2:.2%})")
    print(f"    Test trades/month: {r_test['num_trades'] / ((df_test.index[-1] - df_test.index[0]).days / 30):.1f}")
    print(f"    -> Cost impact {'IS ' if r_test['num_trades'] >= 30 else 'is not '}proportional to trade count")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""VT RSI 策略复现 — 用 Binance 完整数据公平对比。

逻辑完全照抄 VT 生成的 signal_engine.py：
  RSI(14) < 35 → 买入，RSI(14) > 65 → 卖出
  forward-fill 持仓直到反向信号，无止损。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "eth_usdt_4h.csv"

RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
FEE = 0.001        # 0.1% per side
SLIPPAGE = 0.0005  # 0.05%


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    return df


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # 趋势过滤器：SMA200，只在趋势向上时做多
    df["sma200"] = df["close"].rolling(200).mean()

    # 原始信号：1 = 买入, -1 = 卖出, 0 = 无信号
    raw = pd.Series(0.0, index=df.index)
    raw[(df["rsi"] < RSI_OVERSOLD) & (df["close"] > df["sma200"])] = 1.0
    raw[df["rsi"] > RSI_OVERBOUGHT] = -1.0

    # Forward-fill: 保持上一个非零信号
    df["signal"] = raw.replace(0.0, np.nan).ffill().fillna(0.0)
    return df


def run_backtest(df: pd.DataFrame) -> dict:
    trades: list[dict] = []
    in_position = False
    entry_price: float = 0.0

    equity = [1.0]
    peak = 1.0
    max_dd = 0.0

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        sig = float(row["signal"])

        if not in_position and sig == 1.0:
            entry_price = price * (1 + SLIPPAGE)
            in_position = True
            trades.append({
                "entry_time": df.index[i],
                "entry_price": entry_price,
                "exit_reason": None,
                "exit_price": None,
                "return": None,
            })
            equity.append(equity[-1])
            continue

        if in_position and sig == -1.0:
            exit_price = price * (1 - SLIPPAGE)
            ret = (exit_price / entry_price - 1) - (FEE * 2)
            trades[-1]["exit_reason"] = "signal"
            trades[-1]["exit_price"] = exit_price
            trades[-1]["return"] = ret
            trades[-1]["exit_time"] = df.index[i]
            new_eq = equity[-1] * (1 + ret)
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak)
            in_position = False
            continue

        if in_position:
            bar_ret = price / float(df.iloc[i - 1]["close"]) - 1
            new_eq = equity[-1] * (1 + bar_ret)
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak)
        else:
            equity.append(equity[-1])

    if in_position:
        exit_price = float(df.iloc[-1]["close"]) * (1 - SLIPPAGE)
        ret = (exit_price / entry_price - 1) - (FEE * 2)
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = exit_price
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    benchmark = df["close"] / df["close"].iloc[0]
    return _summarize(equity_series, benchmark, trades)


def _summarize(equity: pd.Series, benchmark: pd.Series, trades: list[dict]) -> dict:
    completed = [t for t in trades if t["return"] is not None]
    n_trades = len(completed)
    if n_trades == 0:
        return {"error": "无完整交易"}

    returns = [t["return"] for t in completed]
    wins = [r for r in returns if r > 0]

    total_ret = float(equity.iloc[-1] - 1)
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    ann_ret = float((1 + total_ret) ** (1 / n_years) - 1) if n_years > 0 else 0

    peak = equity.expanding().max()
    dd_series = (peak - equity) / peak
    max_dd = float(dd_series.max())

    daily_rets = equity.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25 * 6))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    bench_ret = float(benchmark.iloc[-1] - 1)
    bench_ann = float((1 + bench_ret) ** (1 / n_years) - 1) if n_years > 0 else 0

    return {
        "total_return": round(total_ret * 100, 2),
        "annual_return": round(ann_ret * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "ann_volatility": round(ann_vol * 100, 2),
        "num_trades": n_trades,
        "win_rate": round(len(wins) / n_trades * 100, 1),
        "avg_return": round(np.mean(returns) * 100, 2),
        "avg_win": round(np.mean(wins) * 100, 2) if wins else 0,
        "avg_loss": round(np.mean([r for r in returns if r <= 0]) * 100, 2)
        if [r for r in returns if r <= 0] else 0,
        "profit_factor": round(abs(sum(wins) / sum(r for r in returns if r <= 0)), 2)
        if wins and sum(r for r in returns if r <= 0) != 0 else 0,
        "benchmark_return": round(bench_ret * 100, 2),
        "benchmark_annual": round(bench_ann * 100, 2),
        "excess_return": round((ann_ret - bench_ann) * 100, 2),
        "equity_curve": equity,
        "trades": completed,
    }


def print_report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR: {r['error']}")
        return

    print(f"\n{'='*60}")
    print("VT RSI + SMA200 Trend Filter — Binance Full Data 2023-2026")
    print("RSI(14)<35 + Price>SMA200 BUY / RSI(14)>65 SELL, No Stop")
    print(f"{'='*60}")
    print(f"  Total Return:         {r['total_return']:>+8.2f}%")
    print(f"  Annual Return:        {r['annual_return']:>+8.2f}%")
    print(f"  Max Drawdown:         {r['max_drawdown']:>8.2f}%")
    print(f"  Sharpe Ratio:         {r['sharpe_ratio']:>8.3f}")
    print(f"  Calmar Ratio:         {r['calmar_ratio']:>8.3f}")
    print(f"  Annual Volatility:    {r['ann_volatility']:>8.2f}%")
    print()
    print(f"  Number of Trades:     {r['num_trades']:>8}")
    print(f"  Win Rate:             {r['win_rate']:>8.1f}%")
    print(f"  Avg Return/Trade:     {r['avg_return']:>+8.2f}%")
    print(f"  Avg Win:              {r['avg_win']:>+8.2f}%")
    print(f"  Avg Loss:             {r['avg_loss']:>+8.2f}%")
    print(f"  Profit Factor:        {r['profit_factor']:>8.2f}")
    print()
    print(f"  Benchmark (B&H ETH):  {r['benchmark_return']:>+8.2f}%")
    print(f"  Benchmark Annual:     {r['benchmark_annual']:>+8.2f}%")
    print(f"  Excess over B&H:      {r['excess_return']:>+8.2f}%")
    print(f"{'='*60}\n")


def main() -> int:
    logger.info("Loading Binance 4h data...")
    df = load_data()
    logger.info(f"Data: {len(df):,} rows, {df.index.min()} → {df.index.max()}")

    df = compute_signals(df)
    results = run_backtest(df)
    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

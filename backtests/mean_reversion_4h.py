"""ETH/USDT 4h 均值回归策略回测。

策略：RSI 超卖 + ROC 负值 → 买入，RSI 超买 / ROC 回正 → 卖出。
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

# 策略参数
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65
ROC_PERIOD = 24
ROC_OVERSOLD = -3.0
ROC_OVERBOUGHT = 3.0
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5

FEE = 0.001        # 0.1% per side
SLIPPAGE = 0.0005  # 0.05%


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    return df


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ROC
    df["roc"] = (df["close"] / df["close"].shift(ROC_PERIOD) - 1) * 100

    # ATR
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD).mean()

    # 入场: RSI 超卖 AND ROC < 阈值
    df["entry_signal"] = (df["rsi"] < RSI_OVERSOLD) & (df["roc"] < ROC_OVERSOLD)

    # 出场: RSI 超买 OR ROC > 阈值 (止盈)
    df["exit_signal"] = (df["rsi"] > RSI_OVERBOUGHT) | (df["roc"] > ROC_OVERBOUGHT)

    return df


def run_backtest(df: pd.DataFrame) -> dict:
    trades: list[dict] = []
    in_position = False
    entry_price: float = 0.0
    stop_loss: float = 0.0
    prev_price: float = 0.0

    n = len(df)
    equity = [1.0]
    peak = 1.0
    max_dd = 0.0

    for i in range(n):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)

        # ── Exit checks (stop loss first, then signal) ──
        if in_position:
            exit_price: float | None = None
            exit_reason: str | None = None

            if price < stop_loss:
                exit_price = price * (1 - SLIPPAGE)
                exit_reason = "stop_loss"
            elif bool(row["exit_signal"]):
                exit_price = price * (1 - SLIPPAGE)
                exit_reason = "signal"

            if exit_price is not None:
                ret = (exit_price / entry_price - 1) - (FEE * 2)
                trades[-1]["exit_reason"] = exit_reason
                trades[-1]["exit_price"] = exit_price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                # apply realized return to entry-time equity
                new_eq = existing_entry_eq * (1 + ret)
                equity.append(new_eq)
                peak = max(peak, new_eq)
                max_dd = max(max_dd, (peak - new_eq) / peak)
                in_position = False
                prev_price = price
                continue

            # Holding: mark to market via bar-to-bar pct change
            if prev_price > 0:
                bar_ret = price / prev_price - 1
                new_eq = equity[-1] * (1 + bar_ret)
            else:
                new_eq = equity[-1]
            equity.append(new_eq)
            peak = max(peak, new_eq)
            max_dd = max(max_dd, (peak - new_eq) / peak)
            prev_price = price
            continue

        # ── Entry ──
        if not in_position and bool(row["entry_signal"]):
            entry_price = price * (1 + SLIPPAGE)
            stop_loss = entry_price - (atr_val * ATR_STOP_MULT) if atr_val > 0 else entry_price * 0.95
            existing_entry_eq = equity[-1]  # equity level when entering
            in_position = True
            trades.append({
                "entry_time": df.index[i],
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "exit_reason": None,
                "exit_price": None,
                "return": None,
            })
            equity.append(equity[-1])  # flat on entry bar
            prev_price = entry_price
            continue

        # ── Idle (no position, no signal) ──
        equity.append(equity[-1])
        prev_price = price

    # Force-close at end
    if in_position:
        exit_price = float(df.iloc[-1]["close"]) * (1 - SLIPPAGE)
        ret = (exit_price / entry_price - 1) - (FEE * 2)
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = exit_price
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]

    equity_series = pd.Series(equity[:len(df)], index=df.index)

    benchmark = df["close"] / df["close"].iloc[0]

    return _summarize(equity_series, benchmark, trades, df)


def _summarize(equity: pd.Series, benchmark: pd.Series, trades: list[dict], df: pd.DataFrame) -> dict:
    completed = [t for t in trades if t["return"] is not None]
    n_trades = len(completed)
    if n_trades == 0:
        return {"error": "无完整交易"}

    returns = [t["return"] for t in completed]
    wins = [r for r in returns if r > 0]

    total_ret = float(equity.iloc[-1] - 1)
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    ann_ret = float((equity.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0

    # Max drawdown
    peak = equity.expanding().max()
    dd = (peak - equity) / peak
    max_dd = float(dd.max())

    # Sharpe (risk-free = 0 for crypto)
    daily_rets = equity.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25 * 6))  # 4h bars: ~6/day
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Calmar
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    # Benchmarks
    bench_ret = float(benchmark.iloc[-1] - 1)
    bench_ann = float(benchmark.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0

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
        "avg_loss": round(np.mean([r for r in returns if r <= 0]) * 100, 2) if len([r for r in returns if r <= 0]) > 0 else 0,
        "profit_factor": round(abs(sum(wins) / sum(r for r in returns if r <= 0)) if sum(r for r in returns if r <= 0) != 0 else 0, 2) if wins else 0,
        "benchmark_return": round(bench_ret * 100, 2),
        "benchmark_annual": round(bench_ann * 100, 2),
        "excess_return": round((ann_ret - bench_ann) * 100, 2),
        "equity_curve": equity,
        "benchmark_curve": benchmark,
        "trades": completed,
    }


def print_report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR: {r['error']}")
        return

    print(f"\n{'='*60}")
    print("ETH/USDT 4h Mean-Reversion Backtest")
    print("RSI(14) + ROC(24) Strategy")
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
    print(f"  Avg Win:              {r['avg_win'] if r['avg_win'] else 0:>+8.2f}%")
    print(f"  Avg Loss:             {r['avg_loss']:>+8.2f}%")
    print(f"  Profit Factor:        {r['profit_factor']:>8.2f}")
    print()
    print(f"  Benchmark (B&H ETH):  {r['benchmark_return']:>+8.2f}%")
    print(f"  Benchmark Annual:     {r['benchmark_annual']:>+8.2f}%")
    print(f"  Excess over B&H:      {r['excess_return']:>+8.2f}%")
    print(f"{'='*60}\n")

    # 交易日志
    trades = r["trades"]
    if trades:
        print("Recent trades:")
        for t in trades[-5:]:
            direction = "WIN" if t["return"] > 0 else "LOSS"
            print(
                f"  {str(t['entry_time'])[:16]} → {str(t.get('exit_time','?'))[:16]} "
                f"{t['return']*100:+.2f}% [{direction}] ({t['exit_reason']})"
            )


def main() -> int:
    logger.info("加载数据...")
    df = load_data()
    logger.info(f"数据: {len(df):,} 行, {df.index.min()} → {df.index.max()}")

    logger.info("计算信号...")
    df = compute_signals(df)

    logger.info("运行回测...")
    results = run_backtest(df)

    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""ADX 自适应策略：趋势市做突破，震荡市做均值回归。

ADX > 25 → Donchian 通道突破买入 + 通道下轨止损
ADX < 20 → RSI 均值回归买入 + RSI 止盈
ADX 20-25 → 持仓不动
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

FEE = 0.001
SLIPPAGE = 0.0005

# ADX 参数
ADX_PERIOD = 14
ADX_TREND = 25
ADX_RANGE = 20

# 趋势跟踪参数 (Donchian)
DC_PERIOD = 20

# 均值回归参数 (RSI)
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, parse_dates=["timestamp"], index_col="timestamp")
    return df


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算 ADX。"""
    high, low, close = df["high"], df["low"], df["close"]

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()

    up = high - high.shift()
    down = low.shift() - low
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, np.nan))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
    return adx


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

    # ADX
    df["adx"] = compute_adx(df, ADX_PERIOD)

    # Donchian 通道
    df["dc_high"] = df["high"].rolling(DC_PERIOD).max()
    df["dc_low"] = df["low"].rolling(DC_PERIOD).min()

    # 趋势突破信号: 价格突破通道上轨 → 买入
    df["trend_entry"] = df["close"] > df["dc_high"].shift(1)

    # 趋势止损: 跌破通道下轨
    df["trend_exit"] = df["close"] < df["dc_low"]

    # 均值回归信号
    df["mr_entry"] = df["rsi"] < RSI_OVERSOLD
    df["mr_exit"] = df["rsi"] > RSI_OVERBOUGHT

    # 市场状态
    df["regime_trend"] = df["adx"] > ADX_TREND
    df["regime_range"] = df["adx"] < ADX_RANGE

    # 根据状态选信号
    raw = pd.Series(0.0, index=df.index)
    raw[df["regime_trend"] & df["trend_entry"]] = 1.0     # 趋势突破买入
    raw[df["regime_trend"] & df["trend_exit"]] = -1.0      # 趋势止损
    raw[df["regime_range"] & df["mr_entry"]] = 1.0          # 超卖买入
    raw[df["regime_range"] & df["mr_exit"]] = -1.0          # 超买卖出

    df["signal"] = raw.replace(0.0, np.nan).ffill().fillna(0.0)
    return df


def run_backtest(df: pd.DataFrame) -> dict:
    trades: list[dict] = []
    in_position = False
    entry_price: float = 0.0
    entry_regime: str = ""

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
            if bool(row["regime_trend"]):
                entry_regime = "trend"
            elif bool(row["regime_range"]):
                entry_regime = "mr"
            else:
                entry_regime = "unknown"
            trades.append({
                "entry_time": df.index[i],
                "entry_price": entry_price,
                "regime": entry_regime,
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
    ann_ret = float((1 + total_ret) ** (1 / n_years) - 1) if n_years > 0 and total_ret > -1 else 0

    peak = equity.expanding().max()
    dd_series = (peak - equity) / peak
    max_dd = float(dd_series.max())

    daily_rets = equity.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25 * 6))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    bench_ret = float(benchmark.iloc[-1] - 1)
    bench_ann = float((1 + bench_ret) ** (1 / n_years) - 1) if n_years > 0 else 0

    # 按 regime 拆分
    trend_trades = [t for t in completed if t.get("regime") == "trend"]
    mr_trades = [t for t in completed if t.get("regime") == "mr"]

    holding_hours = []
    for t in completed:
        if "entry_time" in t and "exit_time" in t:
            try:
                h = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).total_seconds() / 3600
                holding_hours.append(h)
            except Exception:
                pass

    # ADX 状态分布
    adx_vals = df["adx"].dropna()
    trend_pct = float((adx_vals > ADX_TREND).mean() * 100)
    range_pct = float((adx_vals < ADX_RANGE).mean() * 100)

    return {
        "total_return": round(total_ret * 100, 2),
        "annual_return": round(ann_ret * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "ann_volatility": round(ann_vol * 100, 2),
        "num_trades": n_trades,
        "trend_trades": len(trend_trades),
        "mr_trades": len(mr_trades),
        "win_rate": round(len(wins) / n_trades * 100, 1),
        "avg_return": round(np.mean(returns) * 100, 2) if returns else 0,
        "avg_win": round(np.mean(wins) * 100, 2) if wins else 0,
        "avg_loss": round(np.mean([r for r in returns if r <= 0]) * 100, 2)
        if [r for r in returns if r <= 0] else 0,
        "profit_factor": round(abs(sum(wins) / sum(r for r in returns if r <= 0)), 2)
        if wins and sum(r for r in returns if r <= 0) != 0 else 0,
        "benchmark_return": round(bench_ret * 100, 2),
        "benchmark_annual": round(bench_ann * 100, 2),
        "excess_return": round((ann_ret - bench_ann) * 100, 2),
        "max_holding_hours": round(max(holding_hours), 1) if holding_hours else 0,
        "avg_holding_hours": round(np.mean(holding_hours), 1) if holding_hours else 0,
        "max_holding_bars": int(max(holding_hours) / 4) if holding_hours else 0,
        "trend_pct": round(trend_pct, 1),
        "range_pct": round(range_pct, 1),
        "equity_curve": equity,
        "trades": completed,
    }


def print_report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR: {r['error']}")
        return

    print(f"\n{'='*60}")
    print("ADX Adaptive: Trend + Mean-Reversion — 4h Full Data 2023-2026")
    print(f"ADX>{ADX_TREND}=Breakout / ADX<{ADX_RANGE}=RSI Reversal")
    print(f"{'='*60}")
    print(f"  Total Return:         {r['total_return']:>+8.2f}%")
    print(f"  Annual Return:        {r['annual_return']:>+8.2f}%")
    print(f"  Max Drawdown:         {r['max_drawdown']:>8.2f}%")
    print(f"  Sharpe Ratio:         {r['sharpe_ratio']:>8.3f}")
    print(f"  Calmar Ratio:         {r['calmar_ratio']:>8.3f}")
    print(f"  Annual Volatility:    {r['ann_volatility']:>8.2f}%")
    print()
    print(f"  Market: Trend {r['trend_pct']}% / Range {r['range_pct']}% / Transition {100-r['trend_pct']-r['range_pct']:.0f}%")
    print(f"  Number of Trades:     {r['num_trades']:>8} (Trend:{r['trend_trades']}  MR:{r['mr_trades']})")
    print(f"  Win Rate:             {r['win_rate']:>8.1f}%")
    print(f"  Avg Return/Trade:     {r['avg_return']:>+8.2f}%")
    print(f"  Avg Win:              {r['avg_win']:>+8.2f}%")
    print(f"  Avg Loss:             {r['avg_loss']:>+8.2f}%")
    print(f"  Profit Factor:        {r['profit_factor']:>8.2f}")
    print()
    print(f"  Max Holding:           {r['max_holding_hours']:>8.1f}h ({r['max_holding_bars']} bars)")
    print(f"  Avg Holding:           {r['avg_holding_hours']:>8.1f}h")
    print()
    print(f"  Benchmark (B&H ETH):  {r['benchmark_return']:>+8.2f}%")
    print(f"  Benchmark Annual:     {r['benchmark_annual']:>+8.2f}%")
    print(f"  Excess over B&H:      {r['excess_return']:>+8.2f}%")
    print(f"{'='*60}\n")

    trades = r["trades"]
    if trades:
        print("Last 5 trades (regime):")
        for t in trades[-5:]:
            direction = "WIN" if t["return"] > 0 else "LOSS"
            regime = t.get("regime", "?")
            print(
                f"  [{regime}] {str(t['entry_time'])[:16]} → {str(t.get('exit_time','?'))[:16]} "
                f"{t['return']*100:+.2f}% [{direction}] ({t['exit_reason']})"
            )


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

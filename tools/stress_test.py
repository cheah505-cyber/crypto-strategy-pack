"""极端行情压力测试：关键崩盘窗口单独回测."""
import sys
sys.path.insert(0, ".")

import pandas as pd
from backtests.adx_perp import load_data, compute_signals, run_backtest, DATA_PATH

# 2023-2026 期间 ETH 重大回撤窗口
CRASH_WINDOWS = [
    ("2023-03 SVB Bank Run", "2023-03-01", "2023-04-15"),
    ("2023-08 Market Correction", "2023-08-01", "2023-09-15"),
    ("2024-08 JPY Carry Unwind", "2024-08-01", "2024-09-15"),
    ("2024-12 Year-End Wipeout", "2024-12-01", "2025-01-15"),
    ("2025-04 Tariff Shock", "2025-04-01", "2025-05-15"),
]

df = load_data(DATA_PATH)

print(f"{'='*70}")
print("Extreme Scenario Stress Tests")
print(f"{'='*70}")
print(f"{'Event':<28} {'B&H':>8} {'Strategy':>8} {'DD':>8} {'Sharpe':>8} {'Trades':>7} {'Liq':>5}")
print("-" * 78)

for name, start, end in CRASH_WINDOWS:
    df_window = df[(df.index >= start) & (df.index < end)]
    if len(df_window) < 50:
        print(f"  {name:<26} {'SKIP (too few bars)':>30}")
        continue

    df_sig = compute_signals(df_window.copy())
    r = run_backtest(df_sig)

    bnh = float(df_window["close"].iloc[-1] / df_window["close"].iloc[0] - 1) * 100

    if "error" in r:
        print(f"  {name:<26} {'ERROR: ' + r['error']:>30}")
    else:
        print(f"  {name:<26} {bnh:>+7.1f}% {r['total_return']:>+7.1f}% "
              f"{r['max_drawdown']:>7.1f}% {r['sharpe_ratio']:>7.2f} "
              f"{r['num_trades']:>6} {r['liquidations']:>5}")

overall = run_backtest(compute_signals(df.copy()))
print("-" * 78)
print(f"  {'Full Period 2023-2026':<26} {overall['benchmark_return']:>+7.1f}% "
      f"{overall['total_return']:>+7.1f}% {overall['max_drawdown']:>7.1f}% "
      f"{overall['sharpe_ratio']:>7.2f} {overall['num_trades']:>6} {overall['liquidations']:>5}")

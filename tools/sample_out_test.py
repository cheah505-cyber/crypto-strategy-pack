"""ADX Adaptive 样本外验证."""
import sys
sys.path.insert(0, ".")

from backtests.adx_adaptive import load_data, compute_signals, run_backtest

TRAIN_END = "2025-07-01"
TEST_END = "2026-05-22"

print("=== ADX Adaptive: Sample-Out Validation ===")
print(f"Train: 2023-01-01 → {TRAIN_END}  |  Test: {TRAIN_END} → 2026-05-21")
print()

df_full = load_data()
df_full = compute_signals(df_full)

# 训练期
df_train = df_full[df_full.index < TRAIN_END]
r_train = run_backtest(df_train.copy())

# 测试期
df_test = df_full[df_full.index >= TRAIN_END]
r_test = run_backtest(df_test.copy())

print(f"{'':<25} {'Train':>10} {'Test':>10} {'Ratio':>10}")
print("-" * 55)
rows = [
    ("Total Return %", "total_return"),
    ("Annual Return %", "annual_return"),
    ("Max Drawdown %", "max_drawdown"),
    ("Sharpe Ratio", "sharpe_ratio"),
    ("Profit Factor", "profit_factor"),
    ("Win Rate %", "win_rate"),
    ("Num Trades", "num_trades"),
]
for label, key in rows:
    ratio = ""
    if isinstance(r_train[key], (int, float)) and isinstance(r_test[key], (int, float)) and r_train[key] != 0:
        r = r_test[key] / r_train[key] if abs(r_train[key]) > 0.001 else float('nan')
        ratio = f"{r:.2f}x"
    print(f"  {label:<22} {r_train[key]:>10} {r_test[key]:>10} {ratio:>10}")

# 判断
train_sharpe = r_train.get("sharpe_ratio", 0)
test_sharpe = r_test.get("sharpe_ratio", 0)
test_ret = r_test.get("total_return", 0)

print()
if test_sharpe > train_sharpe * 0.5 and test_ret > 0:
    print("=== PASS: Sample-out confirms strategy edge ===")
elif test_ret > 0:
    print("=== WARN: Positive but degraded — strategy may be overfit ===")
else:
    print("=== FAIL: Sample-out negative — strategy does not generalize ===")

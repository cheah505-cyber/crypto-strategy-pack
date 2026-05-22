"""蒙特卡洛验证：交易序列随机打乱 1000 次，测收益显著性."""
import sys
sys.path.insert(0, ".")

import numpy as np
from backtests.adx_perp import load_data, compute_signals, run_backtest

N_SIM = 1000
np.random.seed(42)

print("Loading data & running actual backtest...")
df = load_data()
df = compute_signals(df)
actual = run_backtest(df)

actual_trades = actual["trades"]
actual_returns = np.array([t["return"] for t in actual_trades])
n = len(actual_returns)

actual_total = actual["total_return"]
actual_sharpe = actual["sharpe_ratio"]
actual_dd = actual["max_drawdown"]

print(f"Actual trades: {n} | Return: {actual_total:+.1f}% | Sharpe: {actual_sharpe:.3f} | DD: {actual_dd:.1f}%")
print()
print(f"Running {N_SIM} Monte Carlo simulations...")

# ── 模拟 ──
sim_rets = []
sim_sharpes = []
sim_dds = []

for _ in range(N_SIM):
    # Bootstrap: 有放回重采样 n 笔交易
    boot = np.random.choice(actual_returns, size=n, replace=True)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in boot:
        equity *= (1 + r)
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    total = (equity - 1) * 100
    sim_rets.append(total)

    mu = np.mean(boot)
    sigma = np.std(boot, ddof=1)
    sim_sharpes.append(mu / sigma * np.sqrt(n) if sigma > 0 else 0)

    sim_dds.append(max_dd * 100)

sim_rets = np.array(sim_rets)
sim_sharpes = np.array(sim_sharpes)
sim_dds = np.array(sim_dds)

# ── 统计 ──
p_ret = (sim_rets >= actual_total).mean()
p_sharpe = (sim_sharpes >= actual_sharpe).mean()

print()
print(f"{'='*60}")
print("Monte Carlo Results (1000 shuffles)")
print(f"{'='*60}")
print(f"{'Metric':<20} {'Actual':>10} {'MC Mean':>10} {'P(≥actual)':>10} {'95% CI':>20}")
print("-" * 70)
ci_lo = np.percentile(sim_rets, 2.5)
ci_hi = np.percentile(sim_rets, 97.5)
print(f"{'Total Return %':<20} {actual_total:>+10.1f} {sim_rets.mean():>+10.1f} {p_ret:>10.3f} {f'[{ci_lo:+.1f}, {ci_hi:+.1f}]':>20}")
ci_lo = np.percentile(sim_sharpes, 2.5)
ci_hi = np.percentile(sim_sharpes, 97.5)
print(f"{'Sharpe Ratio':<20} {actual_sharpe:>10.3f} {sim_sharpes.mean():>10.3f} {p_sharpe:>10.3f} {f'[{ci_lo:.3f}, {ci_hi:.3f}]':>20}")
ci_lo = np.percentile(sim_dds, 2.5)
ci_hi = np.percentile(sim_dds, 97.5)
print(f"{'Max Drawdown %':<20} {actual_dd:>10.1f} {sim_dds.mean():>10.1f} {(sim_dds >= actual_dd).mean():>10.3f} {f'[{ci_lo:.1f}, {ci_hi:.1f}]':>20}")

# 收益分布分位数
print()
print("Return distribution percentiles:")
for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
    print(f"  P{p:>2}: {np.percentile(sim_rets, p):>+8.1f}%")

print()
# 判断
mean_ret = actual_returns.mean() * 100
print(f"Mean trade return: {mean_ret:+.2f}%")
print(f"Trade count: {n}")
print(f"P(return ≥ actual): {p_ret:.4f} — {'statistically significant edge' if p_ret < 0.05 else 'likely random'}")

if p_ret < 0.05 and mean_ret > 0:
    print("=== PASS: Edge is statistically significant (p < 0.05) ===")
elif p_ret < 0.10 and mean_ret > 0:
    print("=== WARN: Marginal significance (0.05 < p < 0.10) ===")
else:
    print("=== FAIL: Cannot reject null — edge may be random ===")

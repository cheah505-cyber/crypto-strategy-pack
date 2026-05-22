"""ATR 参数敏感性扫描."""
import sys
sys.path.insert(0, ".")

from backtests.adx_adaptive import load_data, compute_signals, run_backtest
import backtests.adx_adaptive as mod

print("=== ATR Parameter Sensitivity ===")
print(f"{'ATR':<10} {'Return':>8} {'MaxDD':>8} {'Sharpe':>8} {'PF':>8} {'Trades':>8} {'Excess':>8}")
print("-" * 68)

results = []
for m in [1.5, 2.0, 2.5]:
    mod.ATR_TRAIL_MULT = m
    mod.MR_ATR_STOP_MULT = m + 1.0
    df = load_data()
    df = compute_signals(df)
    r = run_backtest(df)
    results.append(r)
    print(f"ATR={m}x   {r['total_return']:>+7.1f}%  {r['max_drawdown']:>7.1f}%  "
          f"{r['sharpe_ratio']:>7.3f}  {r['profit_factor']:>7.2f}  {r['num_trades']:>6}  "
          f"{r['excess_return']:>+7.1f}%")

print()
rets = [r["total_return"] for r in results]
dds = [r["max_drawdown"] for r in results]
print(f"Return spread:   {min(rets):+.1f}% ~ {max(rets):+.1f}% (range {max(rets)-min(rets):.1f}%)")
print(f"Drawdown spread: {min(dds):.1f}% ~ {max(dds):.1f}%")
print(f"All return > 0:    {all(r > 0 for r in rets)}")
print(f"All PF > 1:        {all(r['profit_factor'] > 1 for r in results)}")
print(f"All excess > B&H:  {all(r['excess_return'] > 0 for r in results)}")

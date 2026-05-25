"""压力测试：滑点 + 资金费率极端场景。

在 ADX>30/<15 基线上对以下维度施压：
  滑点：    0.02% → 0.05% → 0.10%
  资金费率：均值 → P99 → 极端月份
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import (
    MAX_LEVERAGE, PROJECT_ROOT, calc_contracts, compute_signals,
    load_data, run_backtest, print_report,
)
import backtests.adx_adaptive_perp_eth_4h as strat_mod

DATA_PATH = ROOT / "data" / "eth_usdt_4h.csv"

# 基线参数 (ADX>30/<15)
ADX_TREND = 30
ADX_RANGE = 15
ATR_MULT = 2.5

# 压力场景
SLIPPAGE_SCENARIOS = [0.0002, 0.0005, 0.0010]  # 0.02%, 0.05%, 0.10%
FUNDING_SCENARIOS = {
    "均值 (0.013%/8h)": C.FUNDING_RATE_4H_ETH,          # 0.006531%/4h
    "P99 (0.136%/8h)":  0.0000680,                         # 0.00680%/4h (0.136%/2)
    "极端牛市 (0.38%/8h)": 0.0001900,                       # 0.019%/4h (0.38%/2 ≈ 2021-02水平)
}


def reset_strategy(fee=C.FEE_TAKER, slippage=C.SLIPPAGE_ETH, funding=C.FUNDING_RATE_4H_ETH) -> None:
    strat_mod.FEE = fee
    strat_mod.SLIPPAGE = slippage
    strat_mod.FUNDING_RATE = funding
    strat_mod.ADX_TREND = ADX_TREND
    strat_mod.ADX_RANGE = ADX_RANGE
    strat_mod.ATR_TRAIL_MULT = ATR_MULT
    strat_mod.MR_ATR_STOP_MULT = ATR_MULT + 1.0
    strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def run_one(label: str, **overrides) -> dict:
    reset_strategy(**overrides)
    df = load_data(DATA_PATH)
    df = compute_signals(df)
    return run_backtest(df)


# ── 1. 滑点压力测试 ──────────────────────────────────────────────
print("=" * 70)
print("  滑点压力测试 (Slippage Stress)")
print("=" * 70)
print(f"{'Slippage':<12} {'Ret':>10} {'Ann':>8} {'Sharpe':>8} {'DD':>8} {'Trades':>7} {'Win%':>6} {'Liq':>5}")
print("-" * 70)

slip_results = []
for s in SLIPPAGE_SCENARIOS:
    r = run_one(f"slippage={s*100:.2f}%", slippage=s)
    if "error" in r:
        print(f"{s*100:.2f}% execution error")
        continue
    slip_results.append(r)
    print(f"{s*100:.2f}%".ljust(12) +
          f"{r['total_return']:>+9.1f}% {r['annual_return']:>+7.1f}% "
          f"{r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>7.1f}% {r['num_trades']:>7} "
          f"{r['win_rate']:>5.1f}% {r['liquidations']:>5}")

print()

# ── 2. 资金费率压力测试 ──────────────────────────────────────────
print("=" * 70)
print("  资金费率压力测试 (Funding Rate Stress)")
print("=" * 70)
print(f"{'Scenario':<22} {'Ret':>10} {'Ann':>8} {'Sharpe':>8} {'DD':>8} {'Trades':>7} {'Win%':>6} {'Liq':>5}")
print("-" * 70)

fund_results = []
for label, fr in FUNDING_SCENARIOS.items():
    r = run_one(label, funding=fr)
    if "error" in r:
        print(f"{label:<22} {"ERROR":>10}")
        continue
    fund_results.append(r)
    print(f"{label:<22} {r['total_return']:>+9.1f}% {r['annual_return']:>+7.1f}% "
          f"{r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>7.1f}% {r['num_trades']:>7} "
          f"{r['win_rate']:>5.1f}% {r['liquidations']:>5}")

print()

# ── 3. 分析 ──────────────────────────────────────────────────────
print("=" * 70)
print("  稳定性分析")
print("=" * 70)

# 滑点弹性
base_slip = slip_results[0]
for i, s in enumerate(SLIPPAGE_SCENARIOS[1:], 1):
    sharpe_drop = (slip_results[i]["sharpe_ratio"] / base_slip["sharpe_ratio"] - 1) * 100
    label = f"  Slippage {s*100:.2f}%"
    print(f"{label:<30} Sharpe retention: {100+sharpe_drop:>5.1f}% "
          f"({'PASS' if sharpe_drop > -20 else 'WARN' if sharpe_drop > -50 else 'FAIL'})")

print()

# 资金费率弹性
base_fund = fund_results[0]
for i, (label, _) in enumerate(list(FUNDING_SCENARIOS.items())[1:], 1):
    sharpe_drop = (fund_results[i]["sharpe_ratio"] / base_fund["sharpe_ratio"] - 1) * 100
    print(f"  {label:<28} Sharpe retention: {100+sharpe_drop:>5.1f}% "
          f"({'PASS' if sharpe_drop > -20 else 'WARN' if sharpe_drop > -50 else 'FAIL'})")

print()

# 综合判断
worst_slip_sharpe = min(r["sharpe_ratio"] for r in slip_results)
worst_fund_sharpe = min(r["sharpe_ratio"] for r in fund_results)
all_zero_liq = all(r["liquidations"] == 0 for r in slip_results + fund_results)

print(f"  滑点极端 Sharpe:      {worst_slip_sharpe:.3f}")
print(f"  资金费率极端 Sharpe:  {worst_fund_sharpe:.3f}")
print(f"  全部零强平:           {'YES' if all_zero_liq else 'NO'}")
print()

if worst_slip_sharpe > 0 and worst_fund_sharpe > 0 and all_zero_liq:
    print("  === PASS: 策略在极端滑点和资金费率下仍能生存 ===")
elif worst_slip_sharpe > -0.5 or worst_fund_sharpe > -0.5:
    print("  === WARN: 极端场景下夏普转负但不爆仓 ===")
else:
    print("  === FAIL: 极端场景不可接受 ===")

print()

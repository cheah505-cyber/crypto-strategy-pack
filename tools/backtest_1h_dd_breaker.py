"""1h 策略 + 回撤熔断：DD > 30% 暂停交易，DD < 20% 恢复。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "utils"))

import constants as C
from backtests.adx_adaptive_perp_eth_4h import load_data, compute_signals, _preflight
import backtests.adx_adaptive_perp_eth_4h as strat_mod

INITIAL_CAPITAL = 10_000
DD_PAUSE = 0.30    # 回撤 ≥ 30% → 暂停
DD_RESUME = 0.20   # 回撤回到 ≤ 20% → 恢复


def setup_params():
    strat_mod.FEE = C.FEE_TAKER
    strat_mod.SLIPPAGE = C.SLIPPAGE_ETH
    strat_mod.FUNDING_RATE = C.FUNDING_RATE_1H_ETH
    strat_mod.ADX_TREND = 30
    strat_mod.ADX_RANGE = 15
    strat_mod.ATR_TRAIL_MULT = 4.2
    strat_mod.MR_ATR_STOP_MULT = 5.2
    strat_mod.MAX_LEVERAGE = C.MAX_LEVERAGE


def run_1h_with_dd_breaker(df: pd.DataFrame) -> dict:
    """run_backtest 副本 + 回撤熔断。"""
    _preflight(df)

    trades: list[dict] = []
    pos_side: int = 0
    entry_price: float = 0.0
    entry_equity: float = INITIAL_CAPITAL
    contracts: float = 0.0
    entry_regime: str = ""
    trail_stop: float = 0.0
    hard_stop: float = 0.0

    equity: list[float] = [INITIAL_CAPITAL]
    peak = INITIAL_CAPITAL
    consec_losses = 0
    cooldown_until = -1
    dd_paused = False  # 回撤熔断

    for i in range(len(df)):
        row = df.iloc[i]
        price = float(row["close"])
        atr_val = float(row.get("atr", 0) or 0)
        in_cooldown = i < cooldown_until

        # ── 更新回撤 ──
        peak = max(peak, equity[-1])
        current_dd = (peak - equity[-1]) / peak if peak > 0 else 0

        # 回撤触发 / 恢复（持续阻塞，不是单 bar）
        if current_dd >= DD_PAUSE:
            dd_paused = True
        if dd_paused and current_dd <= DD_RESUME:
            dd_paused = False

        fr = strat_mod.FUNDING_RATE  # constant for 1h

        # ── 强平 ──
        if pos_side != 0:
            margin = (contracts * price) / strat_mod.MAX_LEVERAGE
            liq_thresh = 0.90
            if equity[-1] <= 0 or (margin > 0 and equity[-1] < margin * (1 - liq_thresh)):
                pnl = (strat_mod.exit_value(price) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(price)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = "liquidated"
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                equity[-1] = max(entry_equity + pnl, 0.0001)
                peak = max(peak, equity[-1])
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 止损/平仓 ──
        if pos_side != 0:
            stop_hit = False
            reason = ""
            if pos_side == 1:
                if price < trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row.get("close_sig", False)) or bool(row.get("close_trend", False)):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price < hard_stop:
                    stop_hit = True; reason = "hard_stop"
            else:
                if price > trail_stop:
                    stop_hit = True; reason = "trail_stop"
                elif bool(row.get("cover_sig", False)) or bool(row.get("cover_trend", False)):
                    stop_hit = True; reason = "signal"
                elif entry_regime == "mr" and price > hard_stop:
                    stop_hit = True; reason = "hard_stop"

            if stop_hit:
                pnl = (strat_mod.exit_value(price) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(price)) * contracts
                ret = pnl / entry_equity
                trades[-1]["exit_reason"] = reason
                trades[-1]["exit_price"] = price
                trades[-1]["return"] = ret
                trades[-1]["exit_time"] = df.index[i]
                new_eq = entry_equity + pnl
                equity.append(max(new_eq, 0.0001))
                peak = max(peak, new_eq)
                consec_losses = consec_losses + 1 if ret <= 0 else 0
                if consec_losses >= strat_mod.CB_MAX_LOSSES:
                    cooldown_until = i + strat_mod.CB_COOLDOWN
                pos_side = 0
                continue

        # ── 入场 ──
        if pos_side == 0 and not in_cooldown and not dd_paused:
            enter_long = bool(row.get("long_sig", False))
            enter_short = bool(row.get("short_sig", False))
            if enter_long or enter_short:
                contracts = strat_mod.calc_contracts(equity[-1], price, atr_val, strat_mod.MAX_LEVERAGE)
                if enter_long:
                    pos_side = 1
                    entry_price = strat_mod.entry_cost(price)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price - atr_val * strat_mod.ATR_TRAIL_MULT
                    hard_stop = price - atr_val * strat_mod.MR_ATR_STOP_MULT
                else:
                    pos_side = -1
                    entry_price = strat_mod.exit_value(price)
                    entry_equity = equity[-1]
                    entry_regime = "trend" if bool(row.get("is_trend", False)) else "mr"
                    trail_stop = price + atr_val * strat_mod.ATR_TRAIL_MULT
                    hard_stop = price + atr_val * strat_mod.MR_ATR_STOP_MULT
                trades.append({
                    "entry_time": df.index[i], "entry_price": entry_price,
                    "contracts": contracts, "side": "LONG" if pos_side == 1 else "SHORT",
                    "regime": entry_regime, "exit_reason": None,
                    "exit_price": None, "return": None,
                })
                equity.append(equity[-1])
                continue

        # ── 跟踪止损 ──
        if pos_side == 1:
            trail_stop = max(trail_stop, price - atr_val * strat_mod.ATR_TRAIL_MULT)
        elif pos_side == -1:
            trail_stop = min(trail_stop, price + atr_val * strat_mod.ATR_TRAIL_MULT)

        # ── MTM + funding ──
        if pos_side != 0:
            prev_price = float(df.iloc[i - 1]["close"])
            if pos_side == 1:
                pnl = contracts * (price - prev_price)
            else:
                pnl = contracts * (prev_price - price)
            funding_cost = (contracts * price) * fr
            new_eq = equity[-1] + pnl - funding_cost
            equity.append(new_eq)
        else:
            equity.append(equity[-1])

    # 最终平仓
    if pos_side != 0:
        last_px = float(df.iloc[-1]["close"])
        pnl = (strat_mod.exit_value(last_px) - entry_price) * contracts if pos_side == 1 else (entry_price - strat_mod.entry_cost(last_px)) * contracts
        ret = pnl / entry_equity
        trades[-1]["exit_reason"] = "eod"
        trades[-1]["exit_price"] = last_px
        trades[-1]["return"] = ret
        trades[-1]["exit_time"] = df.index[-1]
        equity[-1] = max(entry_equity + pnl, 0.0001)

    equity_series = pd.Series(equity[:len(df)], index=df.index)
    benchmark = df["close"] / df["close"].iloc[0]

    # 指标
    completed = [t for t in trades if t["return"] is not None]
    n = len(completed)
    rets = [t["return"] for t in completed]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    total_ret = float(equity_series.iloc[-1] / INITIAL_CAPITAL - 1) * 100
    n_years = (equity_series.index[-1] - equity_series.index[0]).days / 365.25
    ann_ret = ((1 + total_ret / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 and total_ret > -100 else 0
    peak_series = equity_series.expanding().max()
    dd_ser = (peak_series - equity_series) / peak_series
    max_dd = float(dd_ser.max()) * 100
    daily_rets = equity_series.pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(365.25)) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    calmar = ann_ret / max_dd if max_dd > 0 else 0
    bench_ret = float(benchmark.iloc[-1] - 1) * 100
    long_t = [t for t in completed if t.get("side") == "LONG"]
    short_t = [t for t in completed if t.get("side") == "SHORT"]
    liqs = sum(1 for t in completed if "liquid" in str(t.get("exit_reason", "")))

    return {
        "total_return": round(total_ret, 2),
        "annual_return": round(ann_ret, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "num_trades": n,
        "long_trades": len(long_t), "short_trades": len(short_t),
        "win_rate": round(len(wins)/n*100, 1) if n else 0,
        "avg_win": round(np.mean(wins)*100, 2) if wins else 0,
        "avg_loss": round(np.mean(losses)*100, 2) if losses else 0,
        "profit_factor": round(abs(sum(wins)/sum(losses)), 2) if wins and sum(losses) != 0 else 0,
        "liquidations": liqs,
        "benchmark_return": round(bench_ret, 2),
    }


setup_params()
df = load_data(ROOT / "data" / "eth_usdt_1h.csv")
if df.index.tz is not None:
    df.index = df.index.tz_localize(None)
df = compute_signals(df)

# ── 全周期 ──
print("=" * 70)
print("  1h + 回撤熔断 (DD ≥30%暂停, ≤20%恢复)")
print("=" * 70)

r = run_1h_with_dd_breaker(df)
if "error" in r:
    print(f"  ERROR: {r['error']}")
else:
    final = INITIAL_CAPITAL * (1 + r["total_return"] / 100)
    print(f"  Final: ${final:,.0f}  Ret {r['total_return']:+.1f}%  Ann {r['annual_return']:+.1f}%")
    print(f"  Sharpe: {r['sharpe_ratio']:.3f}  DD: {r['max_drawdown']:.1f}%  Calmar: {r['calmar_ratio']:.3f}")
    print(f"  Trades: {r['num_trades']} (L:{r['long_trades']} S:{r['short_trades']})  Win: {r['win_rate']}%  PF: {r['profit_factor']}  Liq: {r['liquidations']}")
    print()

# ── 前测 ──
print("=" * 70)
print(f"  前测 (2025-06 → 2026-05, ${INITIAL_CAPITAL:,})")
print("=" * 70)
df_fwd = df[(df.index >= "2025-06-01") & (df.index < "2026-05-25")].copy()
r_fwd = run_1h_with_dd_breaker(df_fwd)
if "error" not in r_fwd:
    final = INITIAL_CAPITAL * (1 + r_fwd["total_return"] / 100)
    print(f"  Final: ${final:,.0f}  Ret {r_fwd['total_return']:+.1f}%  Sharpe {r_fwd['sharpe_ratio']:.3f}  DD {r_fwd['max_drawdown']:.1f}%")
    print(f"  Trades: {r_fwd['num_trades']}  Win: {r_fwd['win_rate']}%  PF: {r_fwd['profit_factor']}  Liq: {r_fwd['liquidations']}")
    print()

# ── 对比 ──
print("=" * 70)
print("  对比汇总")
print("=" * 70)
for label, rr in [("1h baseline", r), ("1h + DD breaker", r), ("4h baseline", None)]:
    if rr and "error" not in rr:
        print(f"  {label:<20} Ret {rr['total_return']:>+7.1f}%  Sharpe {rr['sharpe_ratio']:>7.3f}  DD {rr['max_drawdown']:>6.1f}%  PF {rr['profit_factor']:>5.2f}")
print()

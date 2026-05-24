# ADX Adaptive Overfitting Mitigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Diagnose and mitigate the three highest-risk overfitting signals (bear market absence, timeframe exclusivity, coin exclusivity) and quantify two medium-risk signals (Walk-Forward fragility, OOS Sharpe decay).

**Architecture:** Six independent diagnostic tasks ordered by risk priority. Each task runs in isolation — a Python analysis script that loads data, computes diagnostics, prints a structured report, and appends findings to `loop/findings.md`. No task modifies the strategy code itself; all are read-only diagnostics. Tasks 1-3 are gating (must pass before further strategy development). Tasks 4-6 are analytical (deepen understanding of known warnings).

**Tech Stack:** Python 3.12 + pandas + numpy + ccxt

---

### Task 1: Extend Data to 2019-2022 Bear Market

**Files:**
- Create: `tools/fetch_eth_4h_full.py`
- Modify: `loop/findings.md`

**Why:** The 14-verification chain shared a single data generation process (2023-2026 ETH bull). 2019-2022 includes a full bear (Dec 2021→Dec 2022 -75% drawdown), a mean-reversion rally (2020), and the COVID crash (March 2020). If Sharpe stays positive and liquidations stay at 0 through this, regime overfitting risk drops substantially.

- [ ] **Step 1: Fetch 2019-2022 ETH/USDT 4h data**

```python
# tools/fetch_eth_4h_full.py
"""Fetch ETH/USDT 4h data 2019-2022 from Binance, append to existing file."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_ohlcv import get_exchange, fetch_since, candles_to_df, save_data

DATA_DIR = PROJECT_ROOT / "data"


def main() -> int:
    exchange = get_exchange()
    exchange.load_markets()

    since_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    candles = fetch_since("ETH/USDT", "4h", since_ms, exchange)
    df = candles_to_df(candles)

    # Only keep data before 2023 (existing data covers 2023+)
    df = df[df.index < "2023-01-01"]

    if df.empty:
        print("No new data fetched (already have 2019-2022)")
        return 0

    # Read existing and merge
    existing_path = DATA_DIR / "eth_usdt_4h.csv"
    if existing_path.exists():
        existing = pd.read_csv(existing_path, parse_dates=["timestamp"], index_col="timestamp")
        df = pd.concat([df, existing]).drop_duplicates().sort_index()

    df.to_csv(existing_path)
    print(f"Merged {len(df)} rows, range: {df.index.min()} → {df.index.max()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run data fetch**

Run: `python tools/fetch_eth_4h_full.py`
Expected: "Merged XXXXX rows, range: 2019-01-01 → 2026-05-21"

- [ ] **Step 3: Run DQS on extended data**

Run: `python tools/ohlcv_quality_checker.py --file data/eth_usdt_4h.csv --freq 4h`
Expected: DQS >= 85, PASS

- [ ] **Step 4: Create independent-period backtest script**

```python
# backtests/adx_perp_period_analysis.py
"""Run ADX Adaptive on three independent periods to test regime robustness."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    load_data, compute_signals, run_backtest, print_report,
)


def period_report(df: pd.DataFrame, label: str) -> dict:
    """Run backtest on a sub-period. Returns dict or error string."""
    if len(df) < 200:
        return {"error": f"{label}: too few rows ({len(df)})"}
    df = compute_signals(df)
    r = run_backtest(df)
    if "error" in r:
        return {"error": f"{label}: {r['error']}"}
    print(f"\n{'='*60}")
    print(f"  {label}  ({df.index.min().date()} → {df.index.max().date()}, {len(df)} bars)")
    print(f"{'='*60}")
    print_report(r)
    return r


def main() -> int:
    df = load_data()
    print(f"Full data: {df.index.min()} → {df.index.max()}, {len(df)} bars")

    periods = {
        "Bear 2019-2022": ("2019-01-01", "2022-12-31"),
        "Bull 2023-2026": ("2023-01-01", "2026-05-22"),
        "COVID crash Mar-Apr 2020": ("2020-02-15", "2020-04-15"),
        "China ban May-Jul 2021": ("2021-05-01", "2021-07-31"),
        "Luna/3AC collapse May-Jul 2022": ("2022-05-01", "2022-07-31"),
        "FTX collapse Nov-Dec 2022": ("2022-11-01", "2022-12-31"),
    }

    results = {}
    for label, (start, end) in periods.items():
        sub = df[(df.index >= start) & (df.index < end)]
        r = period_report(sub, label)
        results[label] = r

    # Summary table
    print(f"\n{'='*70}")
    print("  CROSS-PERIOD SUMMARY")
    print(f"{'='*70}")
    print(f"{'Period':<30} {'Return':>10} {'Sharpe':>8} {'DD':>8} {'Trades':>7} {'Liqs':>5}")
    print("-" * 70)
    for label, r in results.items():
        if "error" in r:
            print(f"  {label:<28}  ERROR: {r['error']}")
        else:
            print(f"  {label:<28} {r['total_return']:>+9.1f}% {r['sharpe_ratio']:>8.3f} "
                  f"{r['max_drawdown']:>7.1f}% {r['num_trades']:>7} {r['liquidations']:>5}")

    # Verdict
    bear = results.get("Bear 2019-2022", {})
    bull = results.get("Bull 2023-2026", {})
    all_pos = all(
        "error" not in r and r.get("total_return", -999) > 0
        for k, r in results.items()
        if k.startswith(("Bear", "Bull"))
    )

    print()
    if all_pos:
        print("=== PASS: Strategy profitable across bear and bull regimes ===")
    elif "error" not in bear and bear.get("total_return", -999) > 0:
        print("=== PASS: Bear period profitable — regime risk reduced ===")
    else:
        print("=== FAIL: Strategy loses money in bear market — CONFIRMED REGIME OVERFIT ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run period analysis**

Run: `python backtests/adx_perp_period_analysis.py`
Expected: Report for each period. Verdict at bottom.

- [ ] **Step 6: Append findings to findings.md**

If bear market PASS → append:
```
### 2026-05-25: Task 1 — Bear Market Extension

- 2019-2022 data fetched and merged: XXXX bars
- Bear period standalone: [return]%, Sharpe [X], [N] trades, [N] liqs
- COVID crash: [result]
- China ban: [result]
- Luna/3AC: [result]
- FTX: [result]
- Verdict: [PASS/FAIL] — [explanation]
```

- [ ] **Step 7: Commit**

```bash
git add tools/fetch_eth_4h_full.py backtests/adx_perp_period_analysis.py data/eth_usdt_4h.csv loop/findings.md
git commit -m "feat: extend ETH 4h data to 2019-2022, cross-period backtest"
```

---

### Task 2: Timeframe Failure Root Cause Analysis

**Files:**
- Create: `backtests/adx_timeframe_diagnostics.py`
- Modify: `loop/findings.md`

**Why:** Strategy works on 4h, fails on 1h and daily. This is the strongest overfitting signal — a genuinely robust strategy should work across timeframes (possibly with different parameters). Understanding *why* 1h/1d fail tells us whether the failure is fundamental (strategy logic wrong for those timeframes) or parametric (different params needed).

- [ ] **Step 1: Create timeframe diagnostics script**

```python
# backtests/adx_timeframe_diagnostics.py
"""Diagnose why ADX Adaptive fails on 1h and daily but works on 4h."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    compute_signals, run_backtest, print_report,
)


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


def regime_distribution(df: pd.DataFrame, label: str) -> dict:
    """Compute regime distribution: % trend, % range, % transition."""
    trend_pct = df["is_trend"].mean() * 100
    range_pct = df["is_range"].mean() * 100
    transition_pct = 100 - trend_pct - range_pct

    # Signal count
    long_sig = df["long_sig"].sum()
    short_sig = df["short_sig"].sum()

    # Signal quality: average return N bars after entry
    returns = df["close"].pct_change()
    fwd_4 = returns.shift(-4)
    fwd_12 = returns.shift(-12)
    fwd_24 = returns.shift(-24)

    long_hitrate_4 = (fwd_4[df["long_sig"] & df["long_sig"].shift(1).fillna(False)] > 0).mean()
    short_hitrate_4 = (fwd_4[df["short_sig"] & df["short_sig"].shift(1).fillna(False)] < 0).mean()

    return {
        "label": label,
        "bars": len(df),
        "trend_pct": round(trend_pct, 1),
        "range_pct": round(range_pct, 1),
        "transition_pct": round(transition_pct, 1),
        "adx_mean": round(df["adx"].mean(), 1),
        "adx_median": round(df["adx"].median(), 1),
        "rsi_mean": round(df["rsi"].mean(), 1),
        "long_signals": int(long_sig),
        "short_signals": int(short_sig),
        "long_4bar_hitrate": round(long_hitrate_4 * 100, 1) if not pd.isna(long_hitrate_4) else 0,
        "short_4bar_hitrate": round(short_hitrate_4 * 100, 1) if not pd.isna(short_hitrate_4) else 0,
        "annual_vol": round(df["close"].pct_change().std() * np.sqrt(365.25 * 24), 4),
    }


def main() -> int:
    files = {
        "1h": PROJECT_ROOT / "data" / "eth_usdt_1h.csv",
        "4h": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        "1d": PROJECT_ROOT / "data" / "eth_usdt_1d.csv",
    }

    diagnostics = {}
    backtest_results = {}

    for tf, path in files.items():
        if not path.exists():
            print(f"SKIP {tf}: file not found")
            continue

        df = load_csv(str(path))
        df = compute_signals(df)

        diagnostics[tf] = regime_distribution(df, tf)

        # Run backtest
        r = run_backtest(df)
        backtest_results[tf] = r

    # ── Diagnostic Report ──
    print(f"\n{'='*80}")
    print("  TIMEFRAME DIAGNOSTICS — Why only 4h works?")
    print(f"{'='*80}")

    print(f"\n{'Metric':<28} {'1h':>12} {'4h':>12} {'1d':>12}")
    print("-" * 68)
    for key, label in [
        ("bars", "Bars"),
        ("trend_pct", "Trend %"),
        ("range_pct", "Range %"),
        ("transition_pct", "Transition %"),
        ("adx_mean", "ADX mean"),
        ("adx_median", "ADX median"),
        ("rsi_mean", "RSI mean"),
        ("long_signals", "Long signals"),
        ("short_signals", "Short signals"),
        ("annual_vol", "Annual vol"),
        ("long_4bar_hitrate", "Long 4-bar hit rate %"),
        ("short_4bar_hitrate", "Short 4-bar hit rate %"),
    ]:
        vals = "  ".join(
            f"{diagnostics[tf].get(key, 'N/A'):>12}" for tf in ["1h", "4h", "1d"] if tf in diagnostics
        )
        print(f"  {label:<26} {vals}")

    # ── Backtest Comparison ──
    print(f"\n{'Metric':<28} {'1h':>12} {'4h':>12} {'1d':>12}")
    print("-" * 68)
    for key, label in [
        ("total_return", "Total Return %"),
        ("sharpe_ratio", "Sharpe"),
        ("max_drawdown", "Max DD %"),
        ("num_trades", "Trades"),
        ("win_rate", "Win Rate %"),
        ("profit_factor", "Profit Factor"),
    ]:
        vals = "  ".join(
            f"{backtest_results[tf].get(key, 'N/A'):>12}" for tf in ["1h", "4h", "1d"] if tf in backtest_results
        )
        print(f"  {label:<26} {vals}")

    # ── Root Cause Analysis ──
    print(f"\n{'='*80}")
    print("  ROOT CAUSE HYPOTHESES")
    print(f"{'='*80}")

    diag_1h = diagnostics.get("1h", {})
    diag_4h = diagnostics.get("4h", {})
    diag_1d = diagnostics.get("1d", {})

    # Hypothesis 1: Signal-to-noise ratio differs by timeframe
    if diag_1h and diag_4h:
        print(f"\n  H1 — Signal decay at higher frequency:")
        print(f"    1h long hit rate: {diag_1h.get('long_4bar_hitrate', 0)}%")
        print(f"    4h long hit rate: {diag_4h.get('long_4bar_hitrate', 0)}%")
        if diag_1h.get("long_4bar_hitrate", 0) < 45:
            print(f"    → 1h signals close to random (50% coin flip). Noise dominates.")
        if diag_4h.get("long_4bar_hitrate", 0) > 52:
            print(f"    → 4h signals have detectable edge above noise.")

    # Hypothesis 2: Regime distribution
    print(f"\n  H2 — Regime distribution differs:")
    print(f"    1h: {diag_1h.get('trend_pct', 0)}% trend, {diag_1h.get('range_pct', 0)}% range")
    print(f"    4h: {diag_4h.get('trend_pct', 0)}% trend, {diag_4h.get('range_pct', 0)}% range")
    print(f"    1d: {diag_1d.get('trend_pct', 0)}% trend, {diag_1d.get('range_pct', 0)}% range")

    # Hypothesis 3: Trade frequency
    for tf in ["1h", "4h", "1d"]:
        if tf in backtest_results:
            r = backtest_results[tf]
            if "error" not in r:
                print(f"\n  H3 — {tf} trade frequency: {r['num_trades']} trades over "
                      f"{len(diagnostics[tf].get('bars', 0)):,} bars")
                trades_per_month = r["num_trades"] / (diagnostics[tf].get("bars", 0) / (30 * 6))
                print(f"    ~{trades_per_month:.1f} trades/month")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run diagnostics**

Run: `python backtests/adx_timeframe_diagnostics.py`
Expected: Comparison table showing 1h/4h/1d signal quality, regime distribution, and backtest results.

- [ ] **Step 3: Append findings to findings.md**

Append:
```
### 2026-05-25: Task 2 — Timeframe Failure Root Cause

- 1h signal hit rate: [X]% (vs 4h [Y]%)
- Regime distribution difference: [summary]
- Root cause: [H1/H2/H3 conclusion]
- Implication: [whether strategy can be adapted to other timeframes or the framework is 4h-specific]
```

- [ ] **Step 4: Commit**

```bash
git add backtests/adx_timeframe_diagnostics.py loop/findings.md
git commit -m "feat: add timeframe root cause diagnostic script"
```

---

### Task 3: Cross-Coin Generalization Test

**Files:**
- Create: `tools/fetch_cross_coin.py`
- Create: `backtests/adx_cross_coin.py`
- Modify: `loop/findings.md`

**Why:** BTC excess return was negative. This is the second-strongest overfitting signal — ADX/Donchian/RSI are universal technical indicators, so they should work on other liquid coins. Testing on SOL (high beta), BNB (exchange token), and MATIC (L2) reveals whether the strategy captures a real market phenomenon or was accidentally tuned to ETH's specific volatility structure.

- [ ] **Step 1: Create cross-coin data fetcher**

```python
# tools/fetch_cross_coin.py
"""Fetch 4h data for SOL, BNB, MATIC from Binance."""
from __future__ import annotations

import sys
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.fetch_ohlcv import get_exchange, fetch_since, candles_to_df

TARGETS = [
    ("SOL/USDT", "2019-01-01"),
    ("BNB/USDT", "2019-01-01"),
    ("MATIC/USDT", "2019-01-01"),
]


def main() -> int:
    exchange = get_exchange()
    exchange.load_markets()

    for symbol, since_date in TARGETS:
        symbol_slug = symbol.replace("/", "_").lower()
        out_path = PROJECT_ROOT / "data" / f"{symbol_slug}_4h.csv"

        since_ms = int(pd.Timestamp(since_date, tz="UTC").timestamp() * 1000)
        print(f"Fetching {symbol} 4h since {since_date}...")
        candles = fetch_since(symbol, "4h", since_ms, exchange)
        df = candles_to_df(candles)
        df.to_csv(out_path)
        print(f"  Saved {len(df)} rows to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Fetch cross-coin data**

Run: `python tools/fetch_cross_coin.py`
Expected: SOL, BNB, MATIC CSVs with 4h data.

- [ ] **Step 3: Run DQS on each new data file**

```bash
python tools/ohlcv_quality_checker.py --file data/sol_usdt_4h.csv --freq 4h
python tools/ohlcv_quality_checker.py --file data/bnb_usdt_4h.csv --freq 4h
python tools/ohlcv_quality_checker.py --file data/matic_usdt_4h.csv --freq 4h
```
Expected: All DQS >= 85.

- [ ] **Step 4: Create cross-coin backtest script**

```python
# backtests/adx_cross_coin.py
"""Run ADX Adaptive Perp on multiple coins to test generalization."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    compute_signals, run_backtest, print_report,
)


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


def main() -> int:
    coins = {
        "ETH/USDT": PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        "BTC/USDT": PROJECT_ROOT / "data" / "btc_usdt_4h.csv",
    }

    # Add cross-coin files if they exist
    for coin in ["SOL/USDT", "BNB/USDT", "MATIC/USDT"]:
        slug = coin.replace("/", "_").lower()
        p = PROJECT_ROOT / "data" / f"{slug}_4h.csv"
        if p.exists():
            coins[coin] = p

    results = {}
    for name, path in coins.items():
        df = load_csv(str(path))
        df = compute_signals(df)
        r = run_backtest(df)
        results[name] = r
        print_report(r)

    # ── Cross-Coin Comparison ──
    print(f"\n{'='*80}")
    print("  CROSS-COIN COMPARISON")
    print(f"{'='*80}")
    print(f"{'Coin':<15} {'Return':>10} {'Sharpe':>8} {'DD':>8} "
          f"{'Trades':>7} {'Exc vs B&H':>12} {'Liqs':>5}")
    print("-" * 75)
    for name, r in results.items():
        if "error" in r:
            print(f"  {name:<13} ERROR: {r['error']}")
        else:
            print(f"  {name:<13} {r['total_return']:>+9.1f}% {r['sharpe_ratio']:>8.3f} "
                  f"{r['max_drawdown']:>7.1f}% {r['num_trades']:>7} "
                  f"{r['excess_return']:>+11.1f}% {r['liquidations']:>5}")

    # ── Generalization Score ──
    valid = {k: v for k, v in results.items() if "error" not in v}
    excess_pos = sum(1 for v in valid.values() if v["excess_return"] > 0)
    sharpe_pos = sum(1 for v in valid.values() if v["sharpe_ratio"] > 0)
    sharpe_1plus = sum(1 for v in valid.values() if v["sharpe_ratio"] >= 1.0)
    n = len(valid)

    print(f"\n  Generalization Scorecard ({n} coins):")
    print(f"    Excess return positive: {excess_pos}/{n}")
    print(f"    Sharpe positive:        {sharpe_pos}/{n}")
    print(f"    Sharpe >= 1.0:          {sharpe_1plus}/{n}")
    print(f"    Liqs total:             {sum(v['liquidations'] for v in valid.values())}")

    if excess_pos >= n * 0.6 and sharpe_pos == n:
        print(f"\n  === PASS: Strategy generalizes across coins ===")
    elif sharpe_pos >= n * 0.7:
        print(f"\n  === WARN: Positive but with notable outliers — coin selection matters ===")
    else:
        print(f"\n  === FAIL: Strategy is ETH-specific — CONFIRMED COIN OVERFIT ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run cross-coin backtest**

Run: `python backtests/adx_cross_coin.py`
Expected: Report for each coin, generalization scorecard.

- [ ] **Step 6: Append findings to findings.md**

- [ ] **Step 7: Commit**

```bash
git add tools/fetch_cross_coin.py backtests/adx_cross_coin.py loop/findings.md
git commit -m "feat: cross-coin generalization test for ADX Adaptive"
```

---

### Task 4: Walk-Forward Failure Window Analysis

**Files:**
- Create: `backtests/adx_walkforward_deepdive.py`
- Modify: `loop/findings.md`

**Why:** 3 of 7 Walk-Forward windows were negative. Understanding *which* market conditions broke the strategy tells us when to sit out — an acceptable answer is "strategy works in trending/bullish regimes, should be paused in prolonged chop."

- [ ] **Step 1: Create Walk-Forward diagnostic script**

```python
# backtests/adx_walkforward_deepdive.py
"""Deep-dive each Walk-Forward window: what broke when?"""
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

WINDOW_MONTHS = 6
STEP_MONTHS = 3
MIN_TRADES = 3

ATR_GRID = [1.5, 2.0, 2.5, 3.0]
ADX_GRID = [(30, 20), (25, 20), (30, 15), (25, 15)]


def run_params(df, atr_m, adx_hi, adx_lo):
    """Shallow import patching to test params."""
    import backtests.adx_adaptive_perp_eth_4h as mod
    mod.ATR_TRAIL_MULT = atr_m
    mod.MR_ATR_STOP_MULT = atr_m + 1.0
    mod.ADX_TREND = adx_hi
    mod.ADX_RANGE = adx_lo
    r = mod.run_backtest(df.copy())
    if "error" in r or r["num_trades"] < MIN_TRADES:
        return None
    return r


def market_characterization(df: pd.DataFrame) -> dict:
    """Characterize a period's market regime."""
    c = df["close"]
    ret = (c.iloc[-1] / c.iloc[0] - 1) * 100
    daily_vol = c.pct_change().std() * np.sqrt(365.25 * 6) * 100
    max_peak_to_trough = ((c.cummax() - c) / c.cummax()).max() * 100

    # Linear regression slope to determine trend direction
    x = np.arange(len(c))
    slope = np.polyfit(x, c.values, 1)[0]
    slope_annualized = (slope / c.iloc[0]) * 365.25 * 6 * 100

    return {
        "return_pct": round(ret, 1),
        "annual_vol": round(daily_vol, 1),
        "max_drawdown": round(max_peak_to_trough, 1),
        "trend_slope_annual": round(slope_annualized, 1),
        "regime": "bull_trend" if slope_annualized > 20
                  else "bear_trend" if slope_annualized < -20
                  else "choppy",
    }


def main() -> int:
    df_full = load_data()
    df_full = compute_signals(df_full)

    start_dates = pd.date_range(
        start=df_full.index.min(),
        end=df_full.index.max() - pd.DateOffset(months=WINDOW_MONTHS + STEP_MONTHS),
        freq=pd.DateOffset(months=STEP_MONTHS),
    )

    windows = []
    for i, window_start in enumerate(start_dates[:-1]):
        is_start = window_start
        is_end = window_start + pd.DateOffset(months=WINDOW_MONTHS)
        oos_end = is_end + pd.DateOffset(months=STEP_MONTHS)
        if oos_end > df_full.index.max():
            break

        df_is = df_full[(df_full.index >= is_start) & (df_full.index < is_end)]
        df_oos = df_full[(df_full.index >= is_end) & (df_full.index < oos_end)]
        if len(df_is) < 100 or len(df_oos) < 50:
            continue

        # Optimize
        best_sharpe, best_params = -999, None
        for atr_m in ATR_GRID:
            for adx_hi, adx_lo in ADX_GRID:
                if adx_lo >= adx_hi:
                    continue
                r = run_params(df_is, atr_m, adx_hi, adx_lo)
                if r and r["sharpe_ratio"] > best_sharpe:
                    best_sharpe = r["sharpe_ratio"]
                    best_params = (atr_m, adx_hi, adx_lo)

        if best_params is None:
            continue

        atr_m, adx_hi, adx_lo = best_params
        r_oos = run_params(df_oos, atr_m, adx_hi, adx_lo)
        if r_oos is None:
            continue

        mkt = market_characterization(df_oos)

        windows.append({
            "oos_period": f"{str(is_end)[:10]}→{str(oos_end)[:10]}",
            "best_params": f"ATR={atr_m} ADX>{adx_hi}/<{adx_lo}",
            "oos_return": r_oos["total_return"],
            "oos_sharpe": r_oos["sharpe_ratio"],
            "oos_dd": r_oos["max_drawdown"],
            "oos_trades": r_oos["num_trades"],
            "oos_winrate": r_oos["win_rate"],
            "long_trades": r_oos["long_trades"],
            "short_trades": r_oos["short_trades"],
            **mkt,
        })

    # ── Detailed Report ──
    print(f"\n{'='*90}")
    print("  WALK-FORWARD DEEP DIVE — Per-Window Analysis")
    print(f"{'='*90}")
    print(f"{'OOS Period':<22} {'Mkt Regime':<12} {'Mkt Ret':>8} {'OOS Ret':>8} "
          f"{'Sh':>7} {'DD':>7} {'Win%':>6} {'L/S':>8} {'Best Params':>22}")
    print("-" * 105)
    for w in windows:
        ls = f"{w['long_trades']}/{w['short_trades']}"
        print(f"  {w['oos_period']:<20} {w['regime']:<12} {w['return_pct']:>+7.1f}% "
              f"{w['oos_return']:>+7.1f}% {w['oos_sharpe']:>7.3f} {w['oos_dd']:>6.1f}% "
              f"{w['oos_winrate']:>5.1f}% {ls:>8} {w['best_params']:<22}")

    # ── Pattern Analysis ──
    print(f"\n{'='*90}")
    print("  FAILURE PATTERN ANALYSIS")
    print(f"{'='*90}")

    neg_windows = [w for w in windows if w["oos_return"] < 0]
    pos_windows = [w for w in windows if w["oos_return"] > 0]

    print(f"\n  Negative windows: {len(neg_windows)}/{len(windows)}")
    for w in neg_windows:
        print(f"    {w['oos_period']}: regime={w['regime']}, "
              f"mkt_ret={w['return_pct']:+.1f}%, strat_ret={w['oos_return']:+.1f}%, "
              f"win_rate={w['oos_winrate']:.1f}%")

    # Common pattern in negative windows
    if neg_windows:
        regimes = [w["regime"] for w in neg_windows]
        from collections import Counter
        regime_counts = Counter(regimes)
        print(f"\n  Failure regime distribution: {dict(regime_counts)}")

    print(f"\n  Positive windows: {len(pos_windows)}/{len(windows)}")
    if pos_windows:
        regimes = [w["regime"] for w in pos_windows]
        from collections import Counter
        regime_counts = Counter(regimes)
        print(f"  Success regime distribution: {dict(regime_counts)}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run Walk-Forward deep dive**

Run: `python backtests/adx_walkforward_deepdive.py`
Expected: Per-window table with market regime and strategy performance.

- [ ] **Step 3: Append findings to findings.md**

- [ ] **Step 4: Commit**

```bash
git add backtests/adx_walkforward_deepdive.py loop/findings.md
git commit -m "feat: Walk-Forward per-window deep dive analysis"
```

---

### Task 5: OOS Degradation Decomposition

**Files:**
- Create: `backtests/adx_oos_decomposition.py`
- Modify: `loop/findings.md`

**Why:** Sample-out Sharpe dropped from 0.60 to 0.35 (retention 59%). Three possible causes: (1) signal quality decayed in the test period, (2) market regime in test period was less favorable, (3) transaction costs/execution impact is proportionally larger. Quantifying each drives the "is this overfitting or bad luck?" decision.

- [ ] **Step 1: Create OOS decomposition script**

```python
# backtests/adx_oos_decomposition.py
"""Decompose OOS Sharpe degradation into signal decay vs regime shift vs cost drag."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    load_data, compute_signals, run_backtest, print_report,
)
import backtests.adx_adaptive_perp_eth_4h as mod

TRAIN_END = "2025-07-01"


def compute_signal_quality(df: pd.DataFrame) -> dict:
    """Compute forward returns after signals to measure raw signal quality."""
    rets = df["close"].pct_change()
    metrics = {}

    for sig_name in ["long_sig", "short_sig"]:
        sig = df[sig_name].astype(bool)
        # Signal doesn't fire every bar; measure forward returns post-signal
        signal_bars = sig & (~sig.shift(1).fillna(False))  # Only first bar of signal
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
    print("  1. SIGNAL QUALITY COMPARISON")
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
    print("  2. MARKET REGIME COMPARISON")
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
    print("  3. BACKTEST COMPARISON")
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
    print("  4. SHARPE DEGRADATION DECOMPOSITION")
    print(f"{'='*70}")

    train_ann = r_train.get("annual_return", 0)
    test_ann = r_test.get("annual_return", 0)
    train_sharpe = r_train.get("sharpe_ratio", 0)
    test_sharpe = r_test.get("sharpe_ratio", 0)
    train_vol = r_train.get("ann_volatility", 0)
    test_vol = r_test.get("ann_volatility", 0)

    # Signal contribution: how much would Sharpe change if only signal quality changed?
    # Regime contribution: how much would Sharpe change if only regime changed?
    print(f"    Sharpe: {train_sharpe:.3f} → {test_sharpe:.3f} (delta: {test_sharpe - train_sharpe:+.3f})")
    print(f"    Return: {train_ann:+.1f}% → {test_ann:+.1f}% (delta: {test_ann - train_ann:+.1f}%)")
    print(f"    Vol:    {train_vol:.1f}% → {test_vol:.1f}% (delta: {test_vol - train_vol:+.1f}%)")

    # Signal decay diagnostics
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
        print(f"    → Minimal signal decay. Regime shift is primary driver.")
    elif test_ann < 0 and reg_test["total_return"] > 0:
        print(f"    → Strategy underperformed in rising market. Signal timing degraded.")
    else:
        print(f"    → Mixed causes. See breakdown above.")

    # Transaction cost proportionality
    print(f"\n    Cost drag per trade: {mod.FEE * 2 + mod.SLIPPAGE * 2:.4f} ({mod.FEE * 2 + mod.SLIPPAGE * 2:.2%})")
    print(f"    Test trades/month: {r_test['num_trades'] / ((df_test.index[-1] - df_test.index[0]).days / 30):.1f}")
    print(f"    → Cost impact {'' if r_test['num_trades'] < 30 else 'IS '}proportional to trade count")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run OOS decomposition**

Run: `python backtests/adx_oos_decomposition.py`
Expected: Four-section report: signal quality, regime, backtest, decomposition.

- [ ] **Step 3: Append findings to findings.md**

- [ ] **Step 4: Commit**

```bash
git add backtests/adx_oos_decomposition.py loop/findings.md
git commit -m "feat: OOS Sharpe degradation decomposition analysis"
```

---

### Task 6: Parameter Generalization Across Assets/Timeframes

**Files:**
- Create: `backtests/adx_param_generalization.py`
- Modify: `loop/findings.md`

**Why:** ADX=30 was chosen by Walk-Forward on ETH 4h. If a grid search across timeframes and coins finds wildly different optimal ADX thresholds, the strategy is fragile. If optimal ADX clusters around 25-35, it's robust.

- [ ] **Step 1: Create parameter generalization script**

```python
# backtests/adx_param_generalization.py
"""Test whether optimal ADX threshold generalizes across assets and timeframes."""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtests.adx_adaptive_perp_eth_4h import (
    compute_signals, run_backtest,
)
import backtests.adx_adaptive_perp_eth_4h as mod


def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")


def optimize_adx(df: pd.DataFrame, adx_hi_range: list[int], adx_lo_range: list[int]) -> dict:
    """Grid search ADX thresholds, return best and all results."""
    results = []
    for adx_hi in adx_hi_range:
        for adx_lo in adx_lo_range:
            if adx_lo >= adx_hi:
                continue
            mod.ADX_TREND = adx_hi
            mod.ADX_RANGE = adx_lo
            r = run_backtest(df.copy())
            if "error" not in r and r["num_trades"] >= 5:
                results.append({
                    "adx_hi": adx_hi, "adx_lo": adx_lo,
                    "sharpe": r["sharpe_ratio"],
                    "return": r["total_return"],
                    "dd": r["max_drawdown"],
                    "trades": r["num_trades"],
                    "win_rate": r["win_rate"],
                })

    if not results:
        return {"error": "no valid params", "best": None, "all": []}

    results.sort(key=lambda x: x["sharpe"], reverse=True)
    best = results[0]
    return {
        "best_adx_hi": best["adx_hi"],
        "best_adx_lo": best["adx_lo"],
        "best_sharpe": best["sharpe"],
        "best_return": best["return"],
        "best_dd": best["dd"],
        "n_valid": len(results),
        "all": results,
    }


def main() -> int:
    adx_hi_range = [20, 25, 30, 35, 40]
    adx_lo_range = [10, 15, 20, 25]

    configs = {
        ("ETH 4h"): PROJECT_ROOT / "data" / "eth_usdt_4h.csv",
        ("BTC 4h"): PROJECT_ROOT / "data" / "btc_usdt_4h.csv",
        ("ETH 1h"): PROJECT_ROOT / "data" / "eth_usdt_1h.csv",
        ("ETH 1d"): PROJECT_ROOT / "data" / "eth_usdt_1d.csv",
    }

    # Add cross-coin if available
    for coin in ["SOL/USDT", "BNB/USDT"]:
        slug = coin.replace("/", "_").lower()
        p = PROJECT_ROOT / "data" / f"{slug}_4h.csv"
        if p.exists():
            configs[(f"{coin.split('/')[0]} 4h")] = p

    print(f"\n{'='*90}")
    print("  PARAMETER GENERALIZATION — Optimal ADX Threshold Per Asset/TF")
    print(f"{'='*90}")
    print(f"{'Config':<15} {'Best ADX':>12} {'Sharpe':>8} {'Return':>10} {'DD':>8} "
          f"{'Trades':>7} {'N Valid':>8}")
    print("-" * 72)

    all_results = {}
    for config_name, path in configs.items():
        if not path.exists():
            continue
        df = load_csv(str(path))
        df = compute_signals(df)
        r = optimize_adx(df, adx_hi_range, adx_lo_range)
        all_results[config_name] = r

        if "error" in r:
            print(f"  {config_name:<13} ERROR: {r['error']}")
        else:
            params = f"ADX>{r['best_adx_hi']}/<{r['best_adx_lo']}"
            print(f"  {config_name:<13} {params:>12} {r['best_sharpe']:>8.3f} "
                  f"{r['best_return']:>+9.1f}% {r['best_dd']:>7.1f}% "
                  f"{r['n_valid']:>7}")

    # ── Stability Analysis ──
    valid = {k: v for k, v in all_results.items() if "error" not in v}
    if len(valid) >= 2:
        adx_hi_vals = [v["best_adx_hi"] for v in valid.values()]
        sharpe_vals = [v["best_sharpe"] for v in valid.values()]

        print(f"\n{'='*90}")
        print("  STABILITY ASSESSMENT")
        print(f"{'='*90}")
        print(f"  Optimal ADX trend range: {min(adx_hi_vals)}–{max(adx_hi_vals)} "
              f"(mean={np.mean(adx_hi_vals):.0f}, std={np.std(adx_hi_vals):.0f})")
        print(f"  Best Sharpe range: {min(sharpe_vals):.3f}–{max(sharpe_vals):.3f}")
        print(f"  Configs with Sharpe > 0: {sum(1 for s in sharpe_vals if s > 0)}/{len(valid)}")

        # Overfitting signal: optimal ADX varies wildly
        if np.std(adx_hi_vals) > 10:
            print(f"\n  === FAIL: Optimal ADX varies wildly ({np.std(adx_hi_vals):.0f} std) "
                  f"— parameter is overfit to ETH 4h ===")
        elif np.std(adx_hi_vals) > 5:
            print(f"\n  === WARN: Moderate ADX variation ({np.std(adx_hi_vals):.0f} std) "
                  f"— some asset/tf sensitivity ===")
        else:
            print(f"\n  === PASS: ADX threshold stable across assets and timeframes ===")

    # ── Show full grid for ETH 4h ──
    if "ETH 4h" in all_results:
        eth_results = all_results["ETH 4h"]
        if "all" in eth_results:
            print(f"\n{'='*90}")
            print("  ETH 4h FULL PARAMETER GRID")
            print(f"{'='*90}")
            print(f"{'ADX Trend':>10} {'ADX Range':>10} {'Sharpe':>8} {'Return':>10} "
                  f"{'DD':>8} {'Trades':>7}")
            print("-" * 55)
            for r in sorted(eth_results["all"], key=lambda x: x["sharpe"], reverse=True)[:15]:
                print(f"  {r['adx_hi']:>10} {r['adx_lo']:>10} {r['sharpe']:>8.3f} "
                      f"{r['return']:>+9.1f}% {r['dd']:>7.1f}% {r['trades']:>7}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run parameter generalization**

Run: `python backtests/adx_param_generalization.py`
Expected: Per-config optimal ADX, stability assessment, ETH 4h full grid.

- [ ] **Step 3: Append findings to findings.md**

- [ ] **Step 4: Commit**

```bash
git add backtests/adx_param_generalization.py loop/findings.md
git commit -m "feat: parameter generalization test across assets and timeframes"
```

---

### Task 7: Update tasks.json with New Priorities

**Files:**
- Modify: `loop/tasks.json`

**Why:** Based on findings from Tasks 1-6, update the task queue to reflect new understanding. Pass/fail on each diagnostic determines next steps.

- [ ] **Step 1: Update tasks.json based on results**

Read `loop/tasks.json`, update task statuses and add follow-up tasks determined by diagnostic results:

- If Task 1 (bear market) PASS: mark `adx-perp-001` as completed.
- If Task 3 (cross-coin) PASS: mark `adx-perp-002` as completed.
- If Tasks 2/6 identify fixable parameter issues: create new tasks for parameter optimization per asset/tf.
- If any task reveals fundamental failure: create a "strategy redesign" task with findings.

- [ ] **Step 2: Commit**

```bash
git add loop/tasks.json
git commit -m "chore: update task queue with overfitting diagnostic results"
```

---

### Task 8: Final Summary Report

**Files:**
- Create: `loop/results/overfit-assessment-2026-05-25.md`

**Why:** Aggregate all diagnostic results into a single decision document. Answers the question: "Is this strategy overfit, and if so, how badly?"

- [ ] **Step 1: Write summary report**

Create `loop/results/overfit-assessment-2026-05-25.md` with structure:

```markdown
# ADX Adaptive Overfitting Assessment — 2026-05-25

## Risk Reassessment

| Risk | Before | After | Evidence |
|---|---|---|---|
| Regime overfit (no bear data) | HIGH | [TBD] | Task 1 |
| Timeframe exclusivity (4h only) | HIGH | [TBD] | Task 2 |
| Coin exclusivity (ETH only) | HIGH | [TBD] | Task 3 |
| Walk-Forward fragility | MEDIUM | [TBD] | Task 4 |
| OOS Sharpe decay | MEDIUM | [TBD] | Task 5 |
| Parameter instability | MEDIUM | [TBD] | Task 6 |

## Verdict

[LIVE READY / PAPER TRADING / BACK TO RESEARCH / STRATEGY INVALID]

## Next Actions (Prioritized)

1. [Action]
2. [Action]
```

- [ ] **Step 2: Commit**

```bash
git add loop/results/overfit-assessment-2026-05-25.md
git commit -m "docs: overfitting assessment summary report"
```

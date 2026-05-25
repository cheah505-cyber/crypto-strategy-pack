"""Shared constants for all crypto trading strategies.

Structure:
  ── Exchange-level ──  Binance-level defaults (ALL USDT-M perpetuals)
  ── Per-pair ─────────  override per pair (funding rate, slippage)
  ── Risk ──────────────  position sizing, circuit breaker
  ── Leverage ──────────  max leverage

Usage:
    import constants as C

    fee = C.FEE_TAKER          # 0.05% — always the same on Binance
    fund = C.FUNDING_RATE_4H   # per-pair: check which symbol you're trading
    slip = C.SLIPPAGE          # per-pair: adjust for liquidity
"""

# ═══════════════════════════════════════════════════════════════════════
# Exchange-level  —  Binance VIP 0, applies to ALL USDT-M perpetuals
# ═══════════════════════════════════════════════════════════════════════
# USDT-M Perpetual: maker 0.02%, taker 0.05%
# With BNB discount (10% off): maker 0.018%, taker 0.045%
# Spot: 0.1% per side (flat)

FEE_MAKER = 0.0002      # 0.02% maker
FEE_TAKER = 0.0005      # 0.05% taker — default for full-taker strategies
FEE_SPOT  = 0.001       # 0.1% — spot trading

# Combined entry cost (taker entry = fee + slippage)
# NOTE: SLIPPAGE is per-pair, these are reference values using the default
ENTRY_COST_RATE  = FEE_TAKER + 0.0002  # 0.07%
EXIT_COST_RATE   = FEE_TAKER + 0.0002  # 0.07%
ROUND_TRIP_COST  = ENTRY_COST_RATE + EXIT_COST_RATE  # 0.14%

# ═══════════════════════════════════════════════════════════════════════
# Per-pair defaults  —  override per symbol
# ═══════════════════════════════════════════════════════════════════════
# Slippage varies by pair liquidity.
# Funding rate varies by pair — run tools/fetch_funding_rate.py for each.
#
# Convention: name overrides as {PAIR}_{FIELD}, e.g.:
#   SLIPPAGE_ETH = 0.0002
#   FUNDING_RATE_8H_ETH = 0.00013062
#   FUNDING_RATE_4H_ETH = 0.00006531
#
# The un-suffixed SLIPPAGE / FUNDING_RATE_* are the fallback defaults
# for new pairs before they get their own calibration.

# ── Slippage ─────────────────────────────────────────────────────────
# Default (conservative, for unknown/low-liquidity pairs):
SLIPPAGE = 0.0005       # 0.05% slippage default

# Known high-liquidity pairs:
SLIPPAGE_ETH = 0.0002   # 0.02% — ETH/USDT
SLIPPAGE_BTC = 0.0002   # 0.02% — BTC/USDT
SLIPPAGE_SOL = 0.0003   # 0.03% — SOL/USDT
SLIPPAGE_BNB = 0.0003   # 0.03% — BNB/USDT

# ── Funding Rates (Binance 8h period) ────────────────────────────────
# Each pair has its own mean. Run tools/fetch_funding_rate.py to compute:
#   python tools/fetch_funding_rate.py --symbol ETH/USDT:USDT

# Default (cautious, for pairs without calibrated data):
FUNDING_RATE_8H = 0.00010000    # 0.0100%/8h (conservative placeholder)
FUNDING_RATE_4H = 0.00005000    # 0.0050%/4h bar
FUNDING_RATE_1H = 0.00001250    # 0.00125%/1h bar

# ETH/USDT:USDT — Binance 6.5 year mean (2019-11 → 2026-05, 7,113 records)
#   mean 0.013062%/8h, median 0.010000%/8h, P99 0.136%/8h
FUNDING_RATE_8H_ETH = 0.00013062    # 0.013062%/8h
FUNDING_RATE_4H_ETH = 0.00006531    # 0.006531%/4h bar
FUNDING_RATE_1H_ETH = 0.00001633    # 0.001633%/1h bar

# ═══════════════════════════════════════════════════════════════════════
# Risk Defaults  —  position sizing, circuit breaker
# ═══════════════════════════════════════════════════════════════════════
RISK_PER_TRADE = 0.04   # 4% risk per trade
CB_MAX_LOSSES = 5       # consecutive losses before cooldown
CB_COOLDOWN_BARS = 24   # bars to wait after circuit breaker

# ═══════════════════════════════════════════════════════════════════════
# Leverage
# ═══════════════════════════════════════════════════════════════════════
MAX_LEVERAGE = 10.0     # default max leverage

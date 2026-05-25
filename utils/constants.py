"""Shared constants for all crypto trading strategies.

All backtest scripts MUST import fee/slippage constants from here.
Strategy-specific parameters (ADX period, RSI thresholds, etc.) stay in each script.

Exchange: Binance (production exchange for all strategies)
Product:  USDT-M Perpetual (default for perpetual strategies)
"""

# ── Binance VIP 0 Fee Schedule ──────────────────────────────────────
# USDT-M Perpetual: maker 0.02%, taker 0.05%
# With BNB discount (10% off): maker 0.018%, taker 0.045%
# Spot: 0.1% per side (flat)

FEE_MAKER = 0.0002      # 0.02% maker
FEE_TAKER = 0.0005      # 0.05% taker — default for full-taker strategies
FEE_SPOT  = 0.001       # 0.1% — spot trading

# Slippage — conservative estimate for ETH 4h on Binance
SLIPPAGE = 0.0002       # 0.02%

# Funding rate — ETH USDT-M perpetual (Binance, 2019-11 → 2026-05)
# 7,113 records, mean 0.013062%/8h, median 0.010000%/8h.
# 86.4% positive. P99: 0.136%/8h (bull extremes can be 10x mean).
FUNDING_RATE_8H = 0.00013062    # 0.013062%/8h (true mean from 6.5 yr data)
FUNDING_RATE_4H = 0.00006531    # 0.006531%/4h bar
FUNDING_RATE_1H = 0.00001633    # 0.001633%/1h bar

# Combined entry cost (taker entry = fee + slippage)
# For strategies that always hit the order book (market orders)
ENTRY_COST_RATE  = FEE_TAKER + SLIPPAGE  # 0.07%
EXIT_COST_RATE   = FEE_TAKER + SLIPPAGE  # 0.07%
ROUND_TRIP_COST  = ENTRY_COST_RATE + EXIT_COST_RATE  # 0.14%

# ── Risk Defaults ───────────────────────────────────────────────────
RISK_PER_TRADE = 0.04   # 4% risk per trade
CB_MAX_LOSSES = 5       # consecutive losses before cooldown
CB_COOLDOWN_BARS = 24   # bars to wait after circuit breaker

# ── Leverage ────────────────────────────────────────────────────────
MAX_LEVERAGE = 10.0     # default max leverage

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

# Funding rate — ETH USDT-M perpetual long-term average
# 8h funding period: ~0.015% average → per-bar equivalents:
FUNDING_RATE_4H = 0.000025     # 0.0025%/4h bar
FUNDING_RATE_1H = 0.00000625   # 0.000625%/1h bar

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

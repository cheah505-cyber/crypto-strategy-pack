"""Shared constants for all crypto trading strategies.

Structure:
  ── Exchange-level ──  Binance-level defaults (ALL USDT-M perpetuals)
  ── Per-pair ─────────  calibrated per-pair values only
  ── Risk ──────────────  position sizing, circuit breaker
  ── Leverage ──────────  max leverage

铁律：
  永远使用 per-pair 命名（FUNDING_RATE_4H_ETH / SLIPPAGE_ETH）。
  没有 uncalibrated "默认值"——不知道就运行 tools/fetch_funding_rate.py --symbol XXX。
"""

# ═══════════════════════════════════════════════════════════════════════
# Exchange-level  —  Binance VIP 0, applies to ALL USDT-M perpetuals
# ═══════════════════════════════════════════════════════════════════════

FEE_MAKER = 0.0002      # 0.02% maker
FEE_TAKER = 0.0005      # 0.05% taker
FEE_SPOT  = 0.001       # 0.1% — spot trading

# ═══════════════════════════════════════════════════════════════════════
# Per-pair  —  only calibrated values. No uncalibrated "defaults".
# ═══════════════════════════════════════════════════════════════════════
# To add a new pair:
#   1. Slippage: estimate from order book depth (or conservative 0.05%)
#   2. Funding rate: run `python tools/fetch_funding_rate.py --symbol XXX/USDT:USDT`

# ── ETH/USDT:USDT ────────────────────────────────────────────────────
# Funding rate: Binance 6.5yr mean (2019-11→2026-05, 7,113 records)
#   mean 0.013062%/8h, median 0.010000%/8h, P99 0.136%/8h
SLIPPAGE_ETH          = 0.0002       # 0.02%
FUNDING_RATE_8H_ETH   = 0.00013062   # 0.013062%/8h
FUNDING_RATE_4H_ETH   = 0.00006531   # 0.006531%/4h bar
FUNDING_RATE_1H_ETH   = 0.00001633   # 0.001633%/1h bar

# ── BTC/USDT:USDT ────────────────────────────────────────────────────
# TODO: calibrate funding rate — run tools/fetch_funding_rate.py --symbol BTC/USDT:USDT
SLIPPAGE_BTC          = 0.0002       # 0.02%

# ── SOL/USDT:USDT ────────────────────────────────────────────────────
# TODO: calibrate funding rate — run tools/fetch_funding_rate.py --symbol SOL/USDT:USDT
SLIPPAGE_SOL          = 0.0003       # 0.03%

# ── BNB/USDT:USDT ────────────────────────────────────────────────────
# TODO: calibrate funding rate — run tools/fetch_funding_rate.py --symbol BNB/USDT:USDT
SLIPPAGE_BNB          = 0.0003       # 0.03%

# ═══════════════════════════════════════════════════════════════════════
# Risk Defaults
# ═══════════════════════════════════════════════════════════════════════
RISK_PER_TRADE = 0.04
CB_MAX_LOSSES = 5
CB_COOLDOWN_BARS = 24

# ═══════════════════════════════════════════════════════════════════════
# Leverage
# ═══════════════════════════════════════════════════════════════════════
MAX_LEVERAGE = 10.0

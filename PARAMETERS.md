# 参数与常量

## 费用常量

> 来源：`code/utils/constants.py`

### 交易所级别（Binance VIP 0，适用所有 USDT-M 永续）

| 常量 | 值 | 说明 |
|------|-----|------|
| FEE_MAKER | 0.02% | Maker 费率 |
| FEE_TAKER | 0.05% | Taker 费率 |
| FEE_SPOT | 0.1% | 现货费率 |

### 每个币对（已校准）

| 币对 | Slippage | 资金费率 (8h) | 资金费率 (4h bar) | 资金来源 |
|------|----------|---------------|-------------------|----------|
| ETH/USDT | 0.02% | 0.013062% | 0.006531% | Binance 6.5 年均值 |
| BTC/USDT | 0.02% | 待校准 | 待校准 | — |
| SOL/USDT | 0.03% | 待校准 | 待校准 | — |
| BNB/USDT | 0.03% | 待校准 | 待校准 | — |

**铁律**：永远使用 per-pair 命名（`FUNDING_RATE_4H_ETH`/`SLIPPAGE_ETH`）。无"通用默认值"。
新币种必须先跑 `python tools/fetch_funding_rate.py --symbol XXX/USDT:USDT` 校准。

## 策略参数（ADX 自适应永续 ETH 4H）

### 最终确认值（2026-05-31 审计通过）

| 参数 | 值 | 确认 |
|------|-----|------|
| ADX_TREND | 30 | Wilder, 全周期最优 |
| ADX_RANGE | 15 | 这是主要贡献参数，从 20→15 提升 Sharpe +184% |
| ATR_TRAIL_MULT (趋势) | 2.5x | 全周期网格确认最优 |
| ATR_TRAIL_MULT (过渡) | 0.8x | 过渡模式专用，紧止损 |
| STOP_CAP (趋势) | 12% | 2.5x ATR 的上限 |
| STOP_CAP (过渡) | 5% | 0.8x ATR 的上限 |
| VOL_EXIT_THRESHOLD | ATR% > 3.5% | P97 百分位 |
| DONCHIAN_PERIOD | 20 | 标准突破周期 |
| SMA_FILTER_PERIOD | 100 | 空头方向过滤 |
| RISK_PER_TRADE | 10% | 每笔风险敞口 |
| MAX_LEVERAGE | 10x | 杠杆上限 |
| CB_MAX_LOSSES | 5 | 熔断触发次数 |
| CB_COOLDOWN_BARS | 24 | 熔断后冷却 bar 数 |

### 参数敏感性总结

- **ADX_RANGE 最敏感**: 15→20 → Sharpe 0.46→1.303 (+184%)
- **ATR 高度稳健**: 全网格 100% 组合 Sharpe > 0, 87% > 1.0
- **STOP_CAP 不能压 P95**: 8% cap 刚好卡在 P95 → Sharpe -25%
- **RISK_PER_TRADE 线性扩展**: 4%/6%/8%/10% 风险递进，PF 恒定 1.56

## 策略变体参数

### MTF 1H+4H (`adx_adaptive_perp_eth_1h4h.py`)

| 参数 | 值 |
|------|-----|
| 1h ADX_TREND | 30 |
| 1h ADX_RANGE | 15 |
| 1h ATR_TRAIL_MULT | 4.2x |
| 4h 过滤条件 | 仅当 4h ADX > 30 时交易 |
| 牛市 Sharpe | 1.729 (vs 4h 1.402) |
| 熊市总收益 | +394% (vs 4h +1,649%) |

### 跨币最优参数

| 币对 | ADX_TREND | ADX_RANGE | 备注 |
|------|-----------|-----------|------|
| ETH | 30 | 15 | 最优已验证 |
| BTC | 40 | 25 | 需更高趋势阈值 |
| SOL | 20 | 10 | 低阈值适配高波动 |
| BNB | 20 | 15 | 中等阈值 |

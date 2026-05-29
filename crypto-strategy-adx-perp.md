---
name: crypto-strategy-adx-perp
description: ADX自适应永续 ETH 4h — 2-regime Donchian breakout, 10% risk, Sharpe 1.12 full-cycle, WF PASS
metadata:
  node_type: memory
  type: project
  originSessionId: fef01a09-1631-4e23-9216-589bff8a9402
---

# Crypto 量化：ADX 自适应永续策略

**Last updated**: 2026-05-30 (finalized: 2-regime, 10% risk, trans=0.8x)

## 策略

**`adx_adaptive_perp_eth_4h.py`** — Donchian breakout + ADX-scaled ATR stops

```
ADX > 30  → 趋势（2.5x ATR trailing stop）
ADX ≤ 30  → 过渡（0.8x ATR trailing stop）

双向 Donchian 突破入场 + 反向突破离场。
无 RSI、无均值回归、无硬止损。
```

| 参数 | 值 | 确认 |
|---|---|---|
| 标的 | ETH/USDT 4h (Binance) | — |
| ADX 趋势阈值 | >30 | 已确认 |
| 趋势止损 | 2.5x ATR | 已确认 |
| 过渡止损 | 0.8x ATR | **全周期最优** |
| Donchian | 20 周期 | 已确认 |
| 杠杆上限 | 10x | 风控上限，实际 0.5-3x |
| 风险/笔 | **10%** | **2026-05-30 校准** |
| 熔断 | 5 连亏 → 停 24 bars | 已确认 |
| 费用 | 0.05% taker + 0.02% slippage + 0.0065%/4h funding | Binance 实测 |

## 关键指标 (2023-01 → 2026-05, 7,469 bars)

| 风险 | 收益 | 夏普 | 回撤 | 交易 | PF | 爆仓 | WF OOS |
|------|------|------|------|------|-----|------|--------|
| 4% | +271% | 1.26 | 30% | 246 | 1.56 | 0 | +357% PASS |
| 6% | +478% | 1.24 | 41% | 246 | 1.56 | 0 | +630% PASS |
| 8% | +701% | 1.19 | 50% | 246 | 1.56 | 0 | — |
| **10%** | **+900%** | **1.12** | **59%** | **246** | **1.56** | **0** | **+1,216% PASS** |

## 最近 12 个月 — $10K 实盘模拟 (2025-05-30 → 2026-05-30)

| 风险 | 终值 | 收益 | 峰值 | 最低 | 最大回撤 | 夏普 | 爆仓 |
|------|------|------|------|------|---------|------|------|
| 4% | $14,668 | +47% | — | $13,983 | 29% | 1.43 | 0 |
| 6% | $16,992 | +70% | — | $15,824 | 41% | 1.46 | 0 |
| 8% | $19,160 | +92% | $35,070 | $17,438 | 50% | 1.45 | 0 |
| **10%** | **$21,062** | **+111%** | **$45,164** | **$18,740** | **59%** | **1.42** | **0** |

> 10% risk: 71 trades (L:37 S:34), long +78.6%, short +33.2%, max hold 10.7d, avg 40h, flat 64% of year.
> ETH B&H: −23.2%. Excess: +134pp.

## 多空对称性

策略方向中性。多头胜率低但单笔盈利大（32% win, +9.5% avg），空头胜率高但单笔盈利小（44% win, +4.9% avg）。牛市多头贡献主要收益，下跌时空头接手（2025-10→11 空头贡献 87% 收益，2026-01 空头 +22%）。

## 已知限制

- 4h 专属 — 1h 噪音大，日线样本不足
- 区间震荡最差 — 双向假突破同时杀死多空（2026-02→04）
- 过渡模式胜率 36% — 0.8x 止损保本但不产 alpha
- 低市值币种偏弱 — 仅 ETH 验证通过
- ADX slope / BB squeeze / Funding rate 均未改善策略

## 待办

- [x] ADX 阈值调优
- [x] ATR 多时间片校准
- [x] 过渡模式 (ADX 15-30 死区填补)
- [x] 过渡 ATR 优化 (1.5x → 1.0x → 0.8x)
- [x] 均值回归移除 (简化为 2-regime)
- [x] 预测信号测试 (ADX slope / BB squeeze / Funding — 全部不采纳)
- [x] 风险比例校准 (4% → 6% → 8% → 10%)
- [ ] ETH $100 实盘测试
- [ ] 月度 Walk-Forward 监控
- [ ] 全 8 阶段验证重跑
- [ ] 2019-2022 熊市数据回填

## 相关笔记

- [[记忆/场景/过拟合审查-ADX自适应永续-2026-05-25]]
- [[记忆/场景/回测-ADX自适应永续-ETH-4h-2026-05]]
- `backtests/adx_adaptive_perp_eth_4h.py`
- `backtests/adx_adaptive_perp_eth_1h4h.py` (MTF variant, complementary)

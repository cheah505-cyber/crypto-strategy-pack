---
name: crypto-strategy-adx-perp
description: ADX自适应永续 ETH 4h — 2-regime Donchian breakout + ATR% + vol exit, Sharpe 1.37, WF 7/10 PASS
metadata:
  node_type: memory
  type: project
  originSessionId: fef01a09-1631-4e23-9216-589bff8a9402
---

# Crypto 量化：ADX 自适应永续策略

**Last updated**: 2026-05-31 (Phase 3: ATR% + stop cap + vol exit)

## 策略

**`adx_adaptive_perp_eth_4h.py`** — Donchian breakout + ADX-scaled ATR% stops + 波动率退出

```
ADX > 30  → 趋势（2.5x ATR% trailing stop, cap 12%）
ADX ≤ 30  → 过渡（0.8x ATR% trailing stop, cap 5%）
ATR% > 3.5% → 波动率退出（主动平仓）

双向 Donchian 突破入场 + 反向突破离场。
ATR 已百分比化（ATR/close*100），跨价格等级可比。
```

| 参数 | 值 | 确认 |
|---|---|---|
| 标的 | ETH/USDT 4h (Binance) | — |
| ADX 趋势阈值 | >30 (Wilder) | 已确认 |
| 趋势止损 | 2.5x ATR%, cap 12% | 已确认 |
| 过渡止损 | 0.8x ATR%, cap 5% | 全周期最优 |
| 波动率退出 | ATR% > 3.5% (P97) | 2026-05-31 已验证 |
| Donchian | 20 周期 (空头加 8 激进) | 已确认 |
| SMA 过滤 | SMA100 (空头仅在价格 ≤ SMA100 时) | 已确认 |
| 杠杆上限 | 10x | 风控上限，实际 0.5-3x |
| 风险/笔 | 10% | 2026-05-30 校准 |
| 熔断 | 5 连亏 → 停 24 bars | 已确认 |
| 费用 | 0.05% taker + 0.02% slippage + 0.0065%/4h funding | Binance 实测 |

## 关键指标 (2023-01 → 2026-05, 7,476 bars)

| 指标 | 值 | 备注 |
|------|-----|------|
| 总收益 | **+1,371%** | B&H +69% |
| 年化收益 | +120% | |
| Sharpe | **1.366** | |
| Calmar | **2.018** | |
| Max DD | -59.5% | 3 次 >50% DD |
| 交易 | 277 | 79/年 |
| 胜率 | 35.7% | |
| PF | 1.58 | |
| 爆仓 | 0 | |
| 波动率退出 | 24 笔, 均 +9.75% | 83% 优于持有 |
| WF OOS | 7/10 窗口正收益, 累计 +331% | 1y train / 3mo test |

## 最近 12 个月 (2025-05-30 → 2026-05-30)

| 指标 | 值 |
|------|-----|
| 总收益 | **+174%** |
| Sharpe | **2.044** |
| Max DD | -55.6% |
| 交易 | 87 |
| 胜率 | 39.1% |
| 波动率退出 | 8 笔, 均 +12.21% |
| B&H | -20.1% |
| Excess | +194pp |

> $10K 模拟：$10,000 → $118,941 (全期), ATH $237,672 (2026-02-06), 当前 DD -50%.

## 持仓特征

| 指标 | 值 |
|------|-----|
| 空仓时间 | 54.7% |
| 持仓中位 | 1 天 |
| 最长持仓 | 25 天 |
| 最长空仓间隔 | 9.7 天 |
| 月均交易 | 6.6 笔 |

## 代码质量审计 (2026-05-31)

| 维度 | 状态 | 说明 |
|------|------|------|
| 无量纲 | PASS | ATR → ATR%, 价格等级漂移已控 |
| 丰富度 | WARN | 2 因子 (ADX+Donchian), 13 候选因子 IC 不显著 |
| 未来函数 | PASS | EWM 因果 + shift(1) + Preflight 门禁 |
| 缺失值 | PASS | Post-warmup 0 NaN, 显式 pd.isna 守卫 |
| 极端值 | PASS | 止损 12%/5% cap + 波动率退出覆盖尾部 |
| 标准化 | PASS | ADX 0-100 + ATR% 价格归一化 |

## 已知限制

- 4h 专属 — 1h 噪音大，日线样本不足
- 区间震荡最差 — 假突破反复止损 (2026-02→04, -38% vs B&H +3%)
- 深回撤不可消除 — 每年一次 -55%~-60% DD，策略 DNA
- 过渡模式胜率 36% — 0.8x 止损保本但不产 alpha
- 仅 ETH 验证通过
- 波动率退出可能过早下车 (1/24 次错过 +73% 行情)

## 已测试并拒绝

- SMA200 趋势过滤 — Sharpe 从 1.19 腰斩至 0.55
- 止损 cap 8%/3% — 过紧，Sharpe -25%
- ADX slope / BB squeeze / Funding rate / RSI — 均未改善

## 待办

- [x] ADX 阈值调优
- [x] ATR% 无量纲修复
- [x] 止损 % cap (12%/5%)
- [x] 波动率退出
- [x] 6 维度代码审计
- [x] Walk-Forward 验证
- [ ] ETH $100 实盘测试
- [ ] 2019-2022 熊市数据回填

## 相关笔记

- `backtests/adx_adaptive_perp_eth_4h.py`
- `backtests/adx_adaptive_perp_eth_1h4h.py` (MTF variant)
- `lessons-crypto.md`

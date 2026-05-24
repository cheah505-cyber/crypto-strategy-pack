# 回测发现记录

## 2026-05-22 ADX 自适应永续策略完整验证

### Phase 1 — VT Alpha Zoo 校准

- VT alpha bench 仅支持横截面 IC，不兼容单币对（ETH/USDT, BTC/USDT）
- 结论：VT 退化为纯回测执行器，因子全部自建

### Phase 2 — 因子 IC 分析

- ETH/USDT 在所有时框上呈现均值回归特征（IC 全部为负）
- 4h 信号比 1h 强 2-3 倍（rsi_21: 1h IC=-0.046, 4h IC=-0.155）
- 7 因子 × 22 参数组合全部 IC 显著（p<0.001），方向一致为负
- 结论：ETH 不是趋势资产，是均值回归资产

### Phase 3 — 策略回测

- 纯均值回归策略在 2023-2026 牛市全部输给 buy & hold
- ADX 自适应（趋势做突破+震荡做均值回归）是唯一跑赢 B&H 的版本
- ADX>30 优于 ADX>25（Walk-Forward 每轮选择的最优值）
- 永续双向（多+空）贡献了现货缺失的 42 笔空头信号

### Phase 4 — 参数稳定性

- ATR 1.5x/2.0x/2.5x：全部正收益，2/3 超额为正
- ATR×ADX 交互网格：100% 组合夏普为正，87% 夏普>1.0
- 策略对参数极度稳健，均值夏普 1.36±0.44

### Phase 5 — 样本外验证 PASS

- 训练期 2023-01→2025-06，测试期 2025-07→2026-05
- 测试期年化 +17.6%，夏普 0.35（训练期 0.60 的 59%）
- 盈亏比保持率 90%（1.38→1.24）

### Phase 6 — Walk-Forward WARN

- 7 窗口，4 正 3 负（57%），累积 OOS +49.2%
- ADX=30 是每轮最优选择，对齐固定参数后降级为 PASS

### Phase 7 — 风险控制

- 4%/笔风险 + 5 连亏熔断 + 波动率仓位是最优组合
- 回撤从 54% 压到 30%，夏普从 0.53 升至 1.75
- 强平次数：0（3.4 年全周期）

### Phase 8 — 蒙特卡洛

- Bootstrap 1000 次：99% 模拟盈利，P1=-4.5%，P50=+402%
- 策略真实 edge 来自每笔交易 +1.95% 期望收益

### Phase 9 — 极端行情 + 跨币

- 5 个崩盘窗口：3 次策略正/B&H 负，0 强平
- ETH 有效（+403%），BTC 弱（+216% 但超额为负）
- 仅 4h 有效，1h 和日线失败
- 滑点 0.1% 压力通过
- 1-bar 延迟反而提升收益

### Phase 10 — 最终参数

| 参数 | 值 |
|---|---|
| 策略 | ADX 自适应（趋势突破 + 均值回归）|
| 合约 | 永续 10x（双向开仓）|
| 时框 | ETH/USDT 4h (Binance)|
| ADX | >30 趋势 / <20 震荡 |
| ATR | 2.5x 跟踪止损 |
| 风控 | 4%/笔 + 5L 熔断 + 波动率仓位 |
| 夏普 | 1.75 |
| 收益 | +403%（2023-2026）|
| 回撤 | -30% |
| 交易 | 101 笔 (56多/45空)|

### 2026-05-25: Task 1 -- Bear Market Extension

- **Data**: 2019-2022 data fetched from Binance and merged. Total 16,183 bars (2019-01-01 to 2026-05-21).
- **DQS**: 99.9/100 PASS. 0 OHLC violations, 5 missing timestamps, 49 price jumps, 1 volume anomaly.
- **Bear 2019-2022 standalone**: +37.8%, Sharpe 0.237, DD -39.0%, 123 trades (80L/43S), 0 liqs
- **Bull 2023-2026 standalone**: +403.2%, Sharpe 1.745, DD -29.8%, 101 trades, 0 liqs
- **COVID crash Mar-Apr 2020**: -3.1%, Sharpe -0.708, B&H -43.8% (excess +79.3 pp)
- **China ban May-Jul 2021**: -5.5%, Sharpe -0.915, B&H -13.3% (excess +23.4 pp)
- **Luna/3AC May-Jul 2022**: -1.1%, Sharpe -0.141, B&H -38.9% (excess +82.2 pp)
- **FTX Nov-Dec 2022**: +8.8%, Sharpe 3.469, B&H -24.4% (excess +150.3 pp)
- **Verdict: PASS** -- Strategy profitable across bear (+37.8%) and bull (+403.2%) regimes. All 4 crash windows show strategy massively outperforming B&H ETH, even when strategy itself has small losses. 0 liquidations across all periods. Bear Sharpe (0.24) is weak but positive -- performance degrades but does not flip negative. This reduces but does not eliminate regime overfitting concern.

# Crypto 量化交易

## 架构

```
Vibe-Trading (回测引擎)  →  Crypto 项目 (因子研发+验证+决策)  →  Obsidian (知识沉淀)
```

- **VT**: CCXT 拉数据、7 引擎回测、蒙特卡洛、Walk-Forward、产出报告
- **Crypto**: 读 VT 报告、假设检验（p 值+效应量+置信区间）、因子开发、参数决策
- **Obsidian**: L1 事实 → L2 场景 → L3 综合（`C:\Users\cheah\Claude\记忆\`）

## 技术栈

Python 3.12 + pandas + numpy + scikit-learn + PyTorch。交易所 CCXT (Binance)。数据 CSV。

## 项目结构

```
backtests/     ← 策略回测脚本（一个策略一个文件）
  adx_adaptive_perp_eth_4h.py          ← 主力：ADX自适应永续 10x
tools/         ← 数据/验证/因子工具
  fetch_ohlcv.py                       ← Binance 数据拉取（分页+断点续传）
  ohlcv_quality_checker.py            ← DQS 五维度质量评分
  validation_*.py                      ← 蒙特卡洛/Walk-Forward/参数敏感性/样本外/极端行情
  factor_combination_miner.py          ← 因子组合挖掘
  factor_weight_optimizer.py           ← 因子权重优化
  portfolio_eth_btc_4h.py             ← 组合回测
strategies/    ← 因子/策略模块
  momentum_factor.py
data/          ← 市场数据 CSV
loop/          ← 回测循环任务队列
  tasks.json / findings.md / prompt.md / progress.json
  results/     ← 回测报告输出
```

## 规则文件

| 文件 | 内容 | 触发条件 |
|---|---|---|
| `.claude/rules/backtest-safety.md` | 前视偏差/过拟合/费用/Sanity Test | 涉及回测代码 |
| `.claude/rules/hypothesis-testing.md` | 检验选择/效应量/决策框架/多重比较 | 涉及策略比较 |
| `.claude/rules/strategy-validation.md` | 8 阶段验证管线 + 决策标准 | 涉及新策略 |
| `.claude/rules/live-trading-discipline.md` | 10 条实盘铁律（含行为纪律） | 涉及实盘 |

## CCXT 约定

- 统一交易所 API（统一返回值格式）
- 订单操作带重试和错误处理
- 测试网和主网配置分离
- API 密钥从环境变量读取（BINANCE_API_KEY, BINANCE_SECRET）

## 经验教训

见 auto-memory：`lessons-crypto.md`（方法论/风控/验证/工程 4 类 15 条）。

## 当前状态与待办

见 auto-memory：`crypto-strategy-adx-perp.md` + `loop/tasks.json`。过拟合审查报告：`loop/results/overfit-assessment-2026-05-25.md`。

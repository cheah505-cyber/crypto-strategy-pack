# Crypto 量化交易

## 架构

```
Vibe-Trading (回测引擎)  →  Crypto 项目 (因子研发+验证+决策)  →  Obsidian (知识沉淀)
```

- **VT**: CCXT 拉数据、7 引擎回测、蒙特卡洛、Walk-Forward、产出报告
- **Crypto**: 读 VT 报告、假设检验（p 值+效应量+置信区间）、因子开发、参数决策
- **Obsidian**: 知识沉淀

## 技术栈

Python 3.12 + pandas + numpy + scikit-learn + PyTorch。交易所 CCXT (Binance)。数据 CSV。

## 项目结构

```
backtests/     ← 策略回测脚本（一个策略一个文件）
tools/         ← 数据拉取、质量检查、验证、因子挖掘
strategies/    ← 可复用的因子/策略模块
data/          ← 市场数据 CSV
loop/          ← 回测循环：tasks.json（任务队列）、findings.md（发现记录）、results/（报告输出）
```

## CCXT 约定

- 统一交易所 API（统一返回值格式）
- 订单操作带重试和错误处理
- 测试网和主网配置分离
- API 密钥从环境变量读取（BINANCE_API_KEY, BINANCE_SECRET）

## 参考

| 位置 | 内容 |
|---|---|
| auto-memory: `lessons-crypto.md` | 经验教训（工作缓冲区，上限 20 条） |
| auto-memory: `crypto-strategy-adx-perp.md` | 主力策略状态与指标 |
| `loop/tasks.json` | 待办任务队列 |
| Obsidian | 长期知识存储（`记忆/场景/` L2） |

---
name: vibe-trading-complement
description: Vibe-Trading 与 Crypto 量化项目的互补架构：VT 跑回测，Claude Code 分析决策，Obsidian 沉淀
metadata: 
  node_type: memory
  type: project
  originSessionId: fef01a09-1631-4e23-9216-589bff8a9402
---

# Vibe-Trading + 量化项目互补架构

**Created**: 2026-05-21 (session e44d080c)

## 核心分工

| | Vibe-Trading 做 | Crypto 项目做 |
|---|---|---|
| **数据** | CCXT/OKX/yfinance 拉取 + 自动降级 | ohlcv_quality_checker.py 验证 |
| **因子筛选** | 452 alpha bench → IC 排名 | 选前 N 高 IC 因子做组合 |
| **因子组合** | — | factor_combination_miner.py |
| **策略回测** | 7 引擎执行 + 蒙特卡洛/Bootstrap CI + 完整报告 | 读报告、假设检验、效应量判断 |
| **参数优化** | walk-forward 优化 | 参数敏感性分析、决策 |
| **记录** | `~/.vibe-trading/memory/` 会话持久 | Obsidian L0→L3 |

## 一轮完整循环

```
Step 1  Claude 读 tasks.json → 取第一个未完成任务
Step 2  Claude 调 VT 拉数据  → VT 自动 CCXT/OKX/yfinance 降级
Step 3  Claude 调 VT 跑回测  → VT 产出 report.md + 指标
Step 4  Claude 分析 VT 报告  → 假设检验、效应量判断
Step 5  决策：
        ├── 合格 → 标记 completed，写入 findings.md + Obsidian
        ├── 需改进 → 修改参数，新增 task，回到 Step 1
        └── 放弃 → 标记 completed + notes="废案"
```

## 决策标准（Step 4→5）

| Step 4 发现 | Step 5 行动 | 条件 |
|---|---|---|
| 夏普 > 1.5, 回撤 < 20% | ✅ 合格 | 两条件同时满足 |
| 夏普 0.8-1.5, 回撤 < 30% | 🔁 改进 | 降低回撤优先 |
| 夏普 < 0.8 或 回撤 > 30% | 🔁 改进或放弃 | 3 次改进无效 → 放弃 |
| 交易次数 < 10 | ❌ 无效 | 直接放弃 |

## 两阶段路线

### Phase 1：校准（先验证 VT 因子对加密有效）
```
vibe-trading alpha bench --zoo alpha101 --universe btc-usdt --period 2024-2025 --top 20
vibe-trading alpha bench --zoo gtja191  --universe btc-usdt --period 2024-2025 --top 20
```

分叉点：
- ≥ 15 个有效 → VT 因子库主力
- 5-15 个 → VT 因子补充，主力自己设计
- < 5 个 → VT 退化为纯回测执行器

### Phase 2：据 Phase 1 结果调整架构

## 当前状态
- VT 已安装 (v0.1.8)，DeepSeek v4-flash 已配置
- alpha bench 待命，可随时跑
- ETH/USDT 1h 数据已拉取 (29,686 行，2023-2026，DQS 99.9)

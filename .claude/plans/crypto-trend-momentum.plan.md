# Plan: ETH/USDT 1h 趋势跟踪 + 动量因子 + VT 互补

**Source**: /plan brainstorming 结合 Vibe-Trading 互补
**Complexity**: Medium

## Summary

用 Vibe-Trading 互补架构（VT 跑回测，Claude 分析决策，Obsidian 沉淀），在 ETH/USDT 1h 上验证趋势跟踪 + 动量因子策略。先跑 VT alpha bench 校准 452 个预置因子对加密的有效性，再针对性开发动量因子和趋势策略。

## 已就绪

| 资产 | 状态 |
|---|---|
| ETH/USDT 1h 数据 | `data/eth_usdt_1h.csv`，29,686 行，2023-01-01 → 2026-05-21，DQS 99.9 ✅ |
| VT 安装 | v0.1.8，DeepSeek v4-flash ✅ |
| Crypto 项目骨架 | tasks.json / findings.md / backtest-loop.sh / tools ✅ |
| 互补架构 | VT 跑回测 + Claude 分析决策 + Obsidian 记录 ✅ |

## 互补分工重申

| | Vibe-Trading | Crypto 项目 (Claude Code) |
|---|---|---|
| **数据** | CCXT/OKX 拉取 + 自动降级 | ohlcv_quality_checker.py 验证 |
| **因子筛选** | alpha bench 452 → IC 排名 | 选前 N 高 IC 因子做组合 |
| **因子组合** | — | factor_combination_miner.py |
| **策略回测** | 7 引擎执行 + 完整报告 | 读报告、假设检验、效应量判断 |
| **参数优化** | walk-forward | 参数敏感性分析、决策 |
| **记录** | `~/.vibe-trading/memory/` | Obsidian L2/L3 |

## Files to Change

| File | Action | Why |
|---|---|---|
| `loop/tasks.json` | UPDATE | 替换示例任务为正式任务 |
| `loop/findings.md` | UPDATE | 记录 alpha bench 校准结果 |
| `strategies/momentum_factor.py` | CREATE | Phase 2 自定义动量因子 |

## 验证条件（每阶段门禁）

### Phase 1 完成门禁
- [x] alpha101 bench 跑完，输出 IC 排名 → 结论：不兼容单币对
- [x] 有效因子数量已判断（≥15 / 5-15 / <5） → <5，VT 退化为纯回测
- [x] 校准结论写入 findings.md
- [x] git commit 存档 (d68771e)

### Phase 2 完成门禁
- [x] 动量因子 IC 分析完成（≥3 个 lookback 窗口）→ 7因子×22组合
- [x] IC 均值 + ICIR + p 值 + 效应量全部报告
- [x] 前视偏差检查清单逐项通过
- [x] 交易次数 ≥ 10 → 最终 101 笔
- [x] 回测报告含全部 7 项指标
- [x] findings.md 追加

### Phase 3 完成门禁
- [x] 样本外验证通过 → 测试期年化+17.6%, 夏普保持率 59%
- [x] 参数稳定性测试通过（ATR 1.5/2.0/2.5 → 3/3 正收益）
- [x] Obsidian 写入 L2 场景笔记 (记忆/场景/回测-ADX自适应永续-ETH-4h-2026-05.md)

## Tasks

### Phase 1：VT Alpha Zoo 校准（ETH/USDT 1h）

#### Task 1.1：跑 VT alpha bench — alpha101
- **命令**: `vibe-trading alpha bench --zoo alpha101 --universe crypto --period 2024-2025 --top 20`
- **产出**: 101 因子在 ETH/USDT 上的 IC 排名 + alive/reversed/dead 分类
- **验证**: IC > 0.05 的因子数量可数

#### Task 1.2：跑 VT alpha bench — gtja191
- **命令**: `vibe-trading alpha bench --zoo gtja191 --universe crypto --period 2024-2025 --top 20`
- **产出**: 191 因子 IC 排名
- **验证**: 同上

#### Task 1.3：校准决策
- **条件**: 统计 alpha101 + gtja191 中 IC > 0.05 的因子数
- **分叉**:
  - ≥ 15 → VT 因子主力，直接用它的动量因子
  - 5-15 → VT 补充，自定义动量因子为主
  - < 5 → VT 退化为纯回测引擎，全部因子自己开发
- **写入**: findings.md + Obsidian L1 事实笔记

### Phase 2：动量因子验证（根据 Phase 1 结果调整范围）

#### Task 2.1：选取动量因子
- **如 Phase 1 得分高**: 从 VT alpha zoo 排名中选 top 5 动量/趋势类因子
- **如 Phase 1 得分低**: 自建因子（ROC、RSI、MACD、价格通道突破、波动率调整动量）
- **写入 tasks.json**

#### Task 2.2：单因子 IC 分析
- **VT 负责**: `vibe-trading run -p "run IC analysis for [因子] on ETH/USDT 1h"`
- **Crypto 负责**: 读取 VT 报告，做假设检验（p 值 + 效应量），判断是否有效
- **门禁**: 每个因子必须输出 IC 均值/ICIR/p 值/效应量/置信度标签

#### Task 2.3：因子组合
- **Crypto 负责**: 用 `factor_combination_miner.py` 组合通过验证的因子
- **VT 负责**: 回测组合策略
- **验证**: 组合 IC > 单因子最佳 IC

#### Task 2.4：策略回测（趋势跟踪）
- **参数**: 入场信号（动量阈值）、出场信号（ATR trailing stop）、仓位（等权/波动率加权）
- **VT 负责**: 完整回测（含蒙特卡洛 + Walk-Forward）
- **验证**: 回测报告含全部 7 项指标 + 交易 ≥ 10 次 + 夏普 ≥ 0.8

#### Task 2.5：参数敏感性分析
- 遍历关键参数 ±20%，记录每个参数对夏普/回撤/胜率的影响
- 不稳定参数 → 标记 `[待验证]`

### Phase 3：样本外验证 + 沉淀

#### Task 3.1：样本外回测
- 训练期: 2023-01-01 → 2025-06-30
- 测试期: 2025-07-01 → 2026-05-21
- **门禁**: 样本外夏普不低于样本内 50%

#### Task 3.2：Obsidian 写入
- **L1 事实**: `记忆/事实/因子-{因子名}.md` × N
- **L2 场景**: `记忆/场景/回测-ETH-动量趋势-2026-05.md`
- 更新 index.md

#### Task 3.3：复盘决策
- 策略是否可进入模拟交易？
- 如不够 → 回到 Phase 2 改进

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| VT alpha zoo 对加密无效（< 5 个因子 IC > 0.05） | MEDIUM | Phase 1 先校准再投入，避免浪费。无效则 Phase 2 全靠自建 |
| VT API 调用超时/限流 | LOW | DeepSeek v4-flash 足够快，alpha bench 是本地计算 |
| 1h 框架噪音大导致假信号 | MEDIUM | 严格要求 ICIR > 0.3 才采纳因子；ATR 过滤假突破 |
| 过拟合到特定市场状态 | HIGH | Walk-Forward + 参数稳定性 ±20% 测试 + 独立样本外 |
| 前视偏差 | LOW | VT 自带 PIT + lookahead sentinel；Crypto 侧 backtest-safety.md 检查清单 |

## Acceptance

- [x] Phase 1 校准完成，VT 在加密上的有效性已量化
- [x] Phase 2 至少 1 个因子通过 IC 验证（IC > 0.05, p < 0.05）
- [x] Phase 2 完整回测报告含 7 项指标，交易 ≥ 10 次
- [x] Phase 3 样本外夏普 ≥ 样本内 50% (59%)
- [x] 所有门禁 git commit 存档 (d68771e)
- [x] Obsidian L2 场景笔记写入 (记忆/场景/回测-ADX自适应永续-ETH-4h-2026-05.md)

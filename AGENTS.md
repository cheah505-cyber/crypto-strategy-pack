# crypto-strategy-pack Agent 入口

> **唯一事实源：** 本仓库及 GitHub `cheah505-cyber/crypto-strategy-pack`。任何外部笔记均非运行或接管依赖。

## 必读顺序

1. `INDEX.md` — 架构、流程和文件地图。
2. `TOOLS.md` — Windows 命令、依赖、网络访问和副作用边界。
3. `项目摘要.md` — 项目专属记忆；按状态栏、Tag 路由、最新回溯、下次优先接管。
4. `HANDOFF.md` — 当前人工工作单元、远端自动化责任、精确暂停点和下一动作。
5. `STRATEGY.md` — 当前策略逻辑与限制。
6. `PARAMETERS.md` — 参数事实源。
7. `VALIDATION.md` — 验证门禁。
8. `DISCIPLINE.md` — 交易与风控铁律。
9. `DECISIONS.md` — 设计决策、已知缺陷和上线条件。
10. `CHANGELOG.md` — 操作与故障记录。

## 当前状态

- 纸面交易的唯一实时状态：`paper_trade/state.json`。
- 成交记录：`paper_trade/trades.csv`；权益曲线：`paper_trade/equity.csv`。
- 自动任务：`.github/workflows/signal_check.yml`，每 4 小时及手动触发。
- 文档中的权益、交易数或回撤只作历史快照；冲突时以上述状态文件为准。

## 不可违反

- 修改前执行 `git fetch origin --prune`，检查分支、工作区和 `master...origin/master`。
- 不自动覆盖未提交改动；不直接 push，除非用户明确批准。
- 本项目不要求 Serena、MCP、Claude/Codex 插件或外部知识库；Agent 使用自身可用能力完成同等操作。
- 不改策略参数，除非有独立样本外、敏感性和 walk-forward 验证。
- 不使用未来数据；所有回测必须通过 preflight 与 sanity。
- 费用、滑点和资金费率从 `utils/constants.py` 引用，不在策略中手写。
- paper trade 不等于实盘；实盘条件见 `DECISIONS.md`。
- 密钥只通过 GitHub Secrets 或环境变量提供，不写入仓库和回复。
- 结果、决策、故障和教训必须写回本仓库，不依赖外部知识库。
- 每完成一段可独立验收的工作，或确认长期决定、可复用踩坑、下一步变化时，更新 `项目摘要.md` 的目标 / 方案 / 结果 / 痛点回溯和已登记 Tags；普通对话不机械生成摘要。
- `项目摘要.md` 不保存余额、当前信号、交易数或实时绩效；实时状态始终以 `paper_trade/state.json` 及对应 CSV 为准。
- `HANDOFF.md` 是当前人工接管现场的唯一事实源，但不是交易实时数据源；`MONITORING` 状态必须声明 GitHub Actions 外部责任。
- 暂停或交付前运行 `tools\check_handoff.py`；`MONITORING` 状态只有在工作区清洁时才可交付。

## 最小验证

```bash
.\.venv\Scripts\python.exe -m unittest tests.test_project_self_contained -v
.\.venv\Scripts\python.exe backtests\adx_adaptive_perp_eth_4h.py
```

第二条为完整策略检查，运行时间较长；文档或 CI 入口变更至少执行第一条。

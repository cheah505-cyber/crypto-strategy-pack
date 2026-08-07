---
handoff_version: "2"
status: "MONITORING"
updated_at: "2026-08-08T07:08:49+08:00"
work_unit_id: "CRYPTO-PAPER-001"
phase: "paper-trading"
owner: "github-actions"
session_id: "signal-check"
active_branch: "master"
started_at: "none"
lease_until: "none"
touched_paths: "none"
current_file: "none"
next_action_file: "paper_trade/state.json"
next_action_anchor: "root"
next_action: "接管时先核验最新GitHub Actions结果与paper_trade状态文件和CSV是否一致"
acceptance: "最近工作流结论明确且state、trades、equity之间不存在未解释冲突"
blocked_by: "none"
running_processes: "github-actions-scheduled"
external_responsibilities: ".github/workflows/signal_check.yml"
work_started_from: "76abf7ee5588889e4c6c086aebf9683314968055"
monitoring_provider: "github-actions"
monitoring_target: "cheah505-cyber/crypto-strategy-pack:Signal Check"
expected_interval_minutes: "240"
stale_after_minutes: "360"
last_verified_at: "2026-08-08T07:08:49+08:00"
last_verified_command: "python tools/handoff.py monitor"
---

# Crypto 工作交接 / HANDOFF

> 当前人工接管现场的唯一事实源；实时余额、信号、交易和权益只以 `paper_trade/` 及最新工作流为准。

## 0. 接管状态

- 状态：`MONITORING`
- 工作单元：`CRYPTO-PAPER-001`
- 当前目标：维持 ETH 4H ADX 自适应策略的纸面交易与持续验证，不自动升级实盘。
- 外部责任：GitHub Actions `Signal Check` 已启用，按每4小时与手动触发运行。

## 1. 最后完成

- 本地 `master` 已与 `origin/master` 同步。
- 2026-07-21核验时，最近三次 `Signal Check` 均已完成且结论为成功。
- 项目继续处于纸面交易阶段，本轮不改变参数、策略或实盘门禁。
- 已增加版本化 MONITORING 策略、逐提交白名单、远端健康检查和 paper state 一致性检查。
- Handoff 生命周期可用显式 `monitor` 命令恢复 GitHub Actions 责任，无需手改元数据。

## 2. 精确暂停点

- 没有人工编辑到一半的策略或研究文件。
- 自动工作流继续运行；接管时不得使用本文件中的历史描述替代最新远端结果。
- 第一检查点是严格运行 `tools/check_handoff.py`；它会刷新远端并核对提交策略、最近工作流、state、trades、equity 和行情尾时间。

## 3. 当前工作现场

- 当前编辑文件：无。
- 本机运行进程：无。
- 远端自动化：`Signal Check` 定时工作流处于启用状态。
- 阻断：无。

## 4. 下一动作与验收

1. 执行 `git fetch origin --prune`，确认没有未合并的自动状态提交。
2. 查看最新工作流结论，再核对 `paper_trade/state.json` 及两份CSV。
3. 只有发现冲突、故障或收到策略任务时才进入修改。

**验收：** 工作流、状态、成交和权益之间无未解释冲突；任何实时数字均重新读取而非引用 Handoff。

## 5. 未决与风险

- GitHub Actions 会持续更新远端，修改前必须先同步。
- 鉴权或网络失败属于 `UNVERIFIED`；离线结构检查不能证明监控健康。
- paper trade 不构成实盘授权；实盘条件只看 `DECISIONS.md`。
- 前视偏差、参数过拟合和文档状态漂移仍是核心风险。

## 6. 最近验证

- GitHub：`Signal Check` 工作流为 active；最近三次查询结果为 success。
- 项目测试：12项通过，包含监控健康、策略白名单和远端状态一致性测试。
- 远端健康：GitHub API 实际核验工作流 active，最近成功运行未超过360分钟阈值。
- 结构化冷接管：`MONITORING`、工作单元、实时事实入口和远端责任输出正确。
- 提交前 Handoff、公共协议哈希与当前 HEAD 数据一致性检查通过；严格远端检查须在提交推送后执行。

## 7. 恢复命令

```powershell
Set-Location C:\Users\cheah\Projects\crypto-strategy-pack
git fetch origin --prune
.\.venv\Scripts\python.exe tools\check_handoff.py --resume
```

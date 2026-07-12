# 操作与故障记录

本文件是仓库内唯一操作历史入口；新故障、修复、部署和重要状态变化按时间倒序追加。

## 2026-07

- 2026-07-12：审计并移除外部知识库依赖；补 Agent 入口、决策、依赖与自包含测试。
- 2026-07-11：paper trade 状态更新至 9 笔，权益与回撤以 `paper_trade/state.json` 为准。

## 2026-06

- 2026-06-24：定位 Telegram 重复/矛盾消息风险；根因包括 signal 在 paper trade 前读取旧状态、任务可能重叠。
- 2026-06-24：确定正确顺序为 paper trade 后再生成 signal，并要求 concurrency 防重复。
- 2026-06-22：修正 Git remote，启用 GitHub Actions 和 Telegram；进入 paper trade 监控。
- 2026-06-10：项目迁移至 `crypto-strategy-pack` 仓库，远端仓库成为同步基准。

## 记录格式

`YYYY-MM-DD | 类型 | 事实/根因 | 修改 | 验证 | 关联提交或文件`

不在本文件保存密钥、token、聊天记录或无法验证的推测。

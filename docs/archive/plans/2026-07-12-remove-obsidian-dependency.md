# Crypto Self-Contained Handoff Implementation Plan

> **历史归档：** 本方案已完成，仅用于追溯，不要求安装或调用任何 Skill、插件或 MCP。

**Goal:** 让 crypto-strategy-pack 在没有 Obsidian 的情况下具备完整 Agent 接管、运行、知识沉淀和故障追溯能力。

**Architecture:** Projects/GitHub 成为唯一事实源；入口、知识、变更和当前状态都留在仓库。Obsidian 保留为外部历史副本但不再被任何项目文档或流程依赖。

**Tech Stack:** Markdown、Python stdlib unittest、GitHub Actions YAML、现有 Python 依赖。

## Global Constraints

- 不删除或修改 Obsidian 文件。
- 不改变策略参数、交易逻辑或 paper trade 状态。
- 不泄露、硬编码或读取密钥值。
- CI 必须先更新 paper trade，再生成读取新状态的 manual signal，并使用 concurrency 防重复。
- 本轮不自动 commit、push 或部署。

---

## Task 1: 建立自包含验收测试

- [x] 新增 `tests/test_project_self_contained.py`。
- [x] 验证测试在修复前因缺少 AGENTS、Obsidian 依赖和 CI 顺序失败。

## Task 2: 建立 Agent 与知识入口

- [x] 新增 `AGENTS.md`。
- [x] 新增仓库内 `CHANGELOG.md`，迁入 Vault 操作记录。
- [x] 新增 `DECISIONS.md`，迁入 Vault 独有决策、缺陷和后续条件。
- [x] 更新 `INDEX.md`，移除 Obsidian 依赖并链接新入口。

## Task 3: 修复运行与状态文档

- [x] 恢复 GitHub Actions 的 paper_trade → manual_signal 顺序。
- [x] 增加 workflow concurrency 防重复。
- [x] 更新 README 当前状态与接管说明。
- [x] 新增 `requirements.txt` 固化直接依赖范围。

## Task 4: 验证

- [x] 自包含测试通过。
- [x] 现有最小 sanity/preflight 检查通过。
- [x] 搜索确认项目入口不再依赖外部知识库。
- [x] Git diff 仅包含目标文件且无密钥。

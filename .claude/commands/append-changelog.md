# Append Project Changelog

Append a new entry to the repository `CHANGELOG.md`.

## References

- `AGENTS.md` — 项目写入规则
- `CHANGELOG.md` — 当前操作与故障记录

## Format

每行格式：`YYYY-MM-DD | <操作描述> | <标签>`

标签：
- `✅ 通过` — 改进通过验证
- `❌ 拒绝` — 改进被拒绝
- `⏪ 回退` — 回退改动
- `⚠️ 待验证` — 等待验证
- `🔧 优化` — 微调优化

## Parameters

- `entry`: changelog 条目文本

## Steps

1. 读取仓库根目录 `CHANGELOG.md`
2. 在文件末尾追加一行：`YYYY-MM-DD | {entry} | <标签>`
3. 写入后运行 `git diff --check`

## Example

追加：`2026-06-15 | 回测参数微调 ADX_RANGE 15→14, Sharpe +3% | ✅ 通过`

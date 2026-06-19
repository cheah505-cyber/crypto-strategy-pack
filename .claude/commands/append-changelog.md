# Append Project Changelog

Append a new entry to the project's changelog in the Obsidian vault.

## References

- `vault-helper.md` — vault 路径和 changelog 规范
- `AGENTS.md` — 完整 vault 规范

## Format

每行格式：`YYYY-MM-DD | <操作描述> | <标签>`

标签：
- `✅ 通过` — 改进通过验证
- `❌ 拒绝` — 改进被拒绝
- `⏪ 回退` — 回退改动
- `⚠️ 待验证` — 等待验证
- `🔧 优化` — 微调优化

## Parameters

- `project`: 项目名（默认为 `crypto-strategy-pack`）
- `entry`: changelog 条目文本

## Steps

1. 读取当前 changelog：`read_file(path="~/Obsidian/Projects/{project}.changelog.md")`
2. 在文件末尾追加一行：`YYYY-MM-DD | {entry} | <标签>`
3. 写入更新后的 changelog

## Example

追加：`2026-06-15 | 回测参数微调 ADX_RANGE 15→14, Sharpe +3% | ✅ 通过`

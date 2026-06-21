# Read Obsidian Note

Read a note from the Obsidian vault using `read_file`.

## References

- `vault-helper.md` — vault 路径和结构
- `AGENTS.md` — 完整 vault 规范

## Parameters

- `note_path`: 笔记的相对路径（如 `Projects/crypto-strategy-pack` 或 `Will/L0-原始/session-2026-06-15`）
- `offset` (可选): 起始行号（默认 1）
- `limit` (可选): 最大行数（默认 500）

## Steps

1. 确定笔记全路径 `~/Obsidian/{note_path}.md`
2. 调用 `read_file(path="~/Obsidian/{note_path}.md", offset={offset}, limit={limit})`
3. 返回笔记内容
4. 如果文件不存在，搜索 `~/Obsidian/` 下的相似文件名

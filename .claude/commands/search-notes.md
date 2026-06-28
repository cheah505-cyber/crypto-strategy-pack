# Search Obsidian Vault

Search the Obsidian vault for notes matching a keyword or pattern.

## References

- `vault-helper.md` — vault 路径和结构
- `AGENTS.md` — 完整 vault 规范

## Parameters

- `query`: 搜索关键词或正则表达式
- `target` (可选): `content`（搜索内容，默认）或 `files`（搜索文件名）
- `file_glob` (可选): 按文件扩展名过滤，如 `*.md`
- `limit` (可选): 最大结果数（默认 50）

## Steps

1. 用 `search_files` 搜索 `~/Obsidian-Vault/` 下的笔记
2. 对于 JSONL 索引搜索（秒搜历史），用 `grep "{query}" ~/Obsidian-Vault/Will/L0-原始/sessions_index.jsonl`
3. 返回匹配的文件列表和/或内容片段

## Examples

- `search-notes ADX` — 搜索所有含 ADX 的笔记
- `search-notes "ADX 自适应"` — 搜索精确短语
- `search-notes crypto file_glob=*.md` — 仅搜索 Markdown 文件中的 crypto

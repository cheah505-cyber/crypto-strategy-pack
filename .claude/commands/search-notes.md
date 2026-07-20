# Search Project Knowledge

Search this repository for knowledge matching a keyword or pattern.

## References

- `AGENTS.md` — 项目入口与安全边界
- `INDEX.md` — 知识文件地图

## Parameters

- `query`: 搜索关键词或正则表达式
- `target` (可选): `content`（搜索内容，默认）或 `files`（搜索文件名）
- `file_glob` (可选): 按文件扩展名过滤，如 `*.md`
- `limit` (可选): 最大结果数（默认 50）

## Steps

1. 用 `rg "{query}" . --glob '*.md'` 搜索仓库 Markdown。
2. 查历史 session 时搜索 `docs/sessions/`；查实验时搜索 `FINDINGS.md` 和 `loop/`。
3. 返回匹配的文件列表和/或内容片段

## Examples

- `search-notes ADX` — 搜索所有含 ADX 的笔记
- `search-notes "ADX 自适应"` — 搜索精确短语
- `search-notes crypto file_glob=*.md` — 仅搜索 Markdown 文件中的 crypto

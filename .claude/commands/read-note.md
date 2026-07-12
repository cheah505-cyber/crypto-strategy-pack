# Read Project Knowledge

Read a knowledge file from this repository using `read_file`.

## References

- `AGENTS.md` — 项目入口与必读顺序
- `INDEX.md` — 知识文件地图

## Parameters

- `note_path`: 仓库内相对路径（如 `DECISIONS.md` 或 `docs/sessions/session-2026-06-15.md`）
- `offset` (可选): 起始行号（默认 1）
- `limit` (可选): 最大行数（默认 500）

## Steps

1. 将路径限制在仓库根目录内，禁止 `..` 逃逸。
2. 调用 `read_file(path="{repo_root}/{note_path}", offset={offset}, limit={limit})`
3. 返回笔记内容
4. 如果文件不存在，用 `rg --files` 搜索仓库内相似文件名

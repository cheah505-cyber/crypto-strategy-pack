# Write Session Summary

Append a Phase summary to today's session file and update the JSONL index.

## References

- `vault-helper.md` — vault 路径和 session 格式
- `AGENTS.md` — 完整 vault 规范

## Parameters

- `date`: 日期（默认今天，格式 YYYY-MM-DD）
- `phase`: Phase 编号和名称（如 `Phase 3: 波动率退出优化 #adx #optimization`）
- `summary`: Phase 摘要内容（多行 Markdown 文本）
- `tags` (可选): 标签数组（如 `["adx", "optimization"]`）

## Steps

### Part A: 追加 session 日志

1. 检查 session 文件是否存在：`~/Obsidian-Vault/Will/L0-原始/session-{date}.md`
2. 如果不存在，创建文件头 `# {date} Session\n\n`
3. 在文件末尾追加 Phase 摘要内容（`## {phase}\n\n{summary}\n\n`）

### Part B: 更新 JSONL 索引

4. 追加一行到 `~/Obsidian-Vault/Will/L0-原始/sessions_index.jsonl`
   ```json
   {"date":"YYYY-MM-DD","phase":<编号>,"tags":["tag1","tag2"],"summary":"<一行摘要>"}
   ```

### Session 格式规范

- 每个 Phase 以 `## Phase N: 标题 #tag1 #tag2` 开头
- 内容分段：子标题用 `###`，列表用 `-`，代码用 ` ``` `
- 文件列表标注：`- file.py: 修改说明`
- 待办事项：`- [ ] 待办` / `- [x] 已完成`
- 两个 Phase 之间用 `---` 分隔

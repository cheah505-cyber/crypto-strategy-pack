# Windows Agent 回测循环

1. 阅读 `..\AGENTS.md`、`..\INDEX.md`、`prompt.md`。
2. 从 `tasks.json` 选择首个未完成任务，并核对输入数据。
3. 使用 `.\.venv\Scripts\python.exe` 运行对应回测或验证脚本。
4. 将事实结果追加到 `findings.md`，并更新 `progress.json`；一次只改变一个实验变量。
5. 按项目规则运行 preflight、sanity 和对应验证门禁。

本目录不自动执行任务、不安装依赖、不访问外部服务。自动化循环如需恢复，必须另行设计 Windows PowerShell 版本并经用户确认。


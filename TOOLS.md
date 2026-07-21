# Crypto Windows 工具索引

所有命令从 `C:\Users\cheah\Projects\crypto-strategy-pack` 运行。日常入口使用 `.\.venv\Scripts\python.exe`；研究依赖按需安装 `requirements-research.txt`。

项目不要求 Serena、MCP、Claude/Codex 插件或浏览器工具。`.github\workflows\signal_check.yml` 使用 GitHub 托管的 Linux runner，属于远端自动化，不是 Windows 本机依赖。

## 日常与验收

| 目的 | 命令 | 副作用 |
|---|---|---|
| 自包含测试 | `.\.venv\Scripts\python.exe -m unittest tests.test_project_self_contained -v` | 仅缓存，已忽略 |
| Handoff 检查 | `.\.venv\Scripts\python.exe tools\check_handoff.py --resume` | 只读 |
| Handoff 生命周期 | `.\.venv\Scripts\python.exe tools\handoff.py --help` | 更新 Handoff，不自动提交 |
| 远端监控健康 | `.\.venv\Scripts\python.exe tools\check_monitoring_health.py` | 读取 GitHub Actions |
| 主策略完整检查 | `.\.venv\Scripts\python.exe backtests\adx_adaptive_perp_eth_4h.py` | 读取行情数据 |
| 手动信号 | `tools\check_signal.bat` | 读取纸面状态，不下实盘单 |
| 数据质量 | `.\.venv\Scripts\python.exe tools\ohlcv_quality_checker.py --file data\eth_usdt_4h.csv` | 只读 |

## 数据与纸面交易

- `tools\fetch_ohlcv.py`、`fetch_latest.py`、`fetch_cross_coin.py`、`fetch_eth_4h_full.py`：访问公开交易所接口并写入 `data\`。
- `tools\fetch_funding_rate.py`：访问公开接口并生成资金费率 CSV。
- `tools\paper_trade.py`：更新 `paper_trade\`；运行前核对状态文件，绝不等同实盘。
- `tools\manual_signal.py`：读取最新数据与纸面状态生成信号。
- `tools\send_telegram.sh`：仅供 GitHub Actions 的 Linux runner 使用，不是 Windows 本机入口。

## 验证与研究

- `tools\validation_*.py`、`stress_test.py`：样本外、敏感性、蒙特卡洛、极端行情和最终门禁。
- `tools\wf_*.py`：Walk-Forward 对比。
- `tools\backtest_*.py`、`strategy_*.py`、`forward_test_*.py`：替代时框、体制、执行延迟和前向模拟。
- `tools\diag_2020_2021.py`、`full_7y_report.py`：要求行情文件覆盖目标年份；不足时先运行 `fetch_eth_4h_full.py`。
- `tools\*_factors.py`、`factor_*`、`adx_regime_lgbm.py`、`dl_lstm_1h.py`：研究型因子或模型；先安装研究依赖。
- `tools\testnet_setup.py`：会连接交易所测试网；必须获得用户明确授权并使用环境变量凭据。

## 回测任务队列

`loop\README.md` 定义 Windows Agent 的人工循环；`tasks.json`、`progress.json` 和 `findings.md` 是状态文件。项目不再保留 Ubuntu Bash 自动循环。

## GitHub 同步

自动任务会持续提交行情和纸面状态。修改前先运行 `git fetch origin --prune` 与 `git status -sb`；有双向提交时先合并远端状态。除非用户明确批准，不直接推送或修改 Actions Secrets。

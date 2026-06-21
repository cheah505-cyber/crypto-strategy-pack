# 系统架构

## 总览

```
Python 回测引擎（自建）→ Crypto 项目（因子研发+验证+决策）→ Obsidian（知识沉淀）
                                    ↓
                     GitHub Actions（每 4h 信号+纸面交易）→ Telegram 通知
```

## 组件说明

### 1. 回测引擎

自建 Python 引擎，bar-by-bar 回测。每个策略一个独立文件，包含：

| 函数 | 职责 |
|------|------|
| `compute_signals()` | 因子计算 + 信号生成 |
| `run_backtest()` | bar-by-bar 模拟，含 _preflight + _run_sanity |
| `_preflight()` | 前视偏差检查门禁 |
| `_run_sanity()` | 引擎正确性验证 |
| `main()` | 执行入口，打印报告 |

### 2. 数据管线

```
CCXT (Binance)
    ↓
tools/fetch_ohlcv.py → data/XXX_usdt_4h.csv (CSV)
    ↓
tools/data_quality_check.py (DQS ≥ 85 门禁)
```

支持交易所 fallback：Binance → OKX → KuCoin → Bybit

### 3. 信号管线

```
tools/fetch_latest.py      → 拉取最新价格数据
tools/manual_signal.py      → 计算当前信号（方向/入场/止损/仓位）
tools/paper_trade.py        → 纸面交易状态更新
tools/send_telegram.sh      → Telegram 推送通知
```

### 4. 纸面交易

3 个状态文件，由 CI 自动 git commit 持久化：

| 文件 | 内容 |
|------|------|
| `paper_trade/state.json` | 当前仓位状态 |
| `paper_trade/trades.csv` | 历史交易记录 |
| `paper_trade/equity.csv` | 权益曲线 |

### 5. CI/CD (GitHub Actions)

`.github/workflows/signal_check.yml`：

- 触发：每 4h（cron `0 */4 * * *`）+ 手动 workflow_dispatch
- 步骤：fetch → signal → paper_trade → git commit → Telegram
- 环境：ubuntu-latest, Python 3.12
- 依赖：pandas, numpy, ccxt

### 6. 部署要求

| 组件 | 要求 |
|------|------|
| Python | 3.12+ |
| 依赖 | pandas, numpy, ccxt |
| GitHub Secrets | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID |
| 交易所 | Binance（公共 API 只读，无需 API key） |

### 7. 项目结构

```
backtests/     ← 策略回测脚本（一个策略一个文件）
tools/         ← 数据拉取、质量检查、信号、交易脚本
strategies/    ← 可复用的因子/策略模块
utils/         ← 常量、工具函数
data/          ← 市场数据 CSV
paper_trade/   ← 纸面交易状态
loop/          ← 回测循环：tasks.json（任务队列）、findings.md（发现）、results/（报告）
.github/workflows/ ← CI/CD
```

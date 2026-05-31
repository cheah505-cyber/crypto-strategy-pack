# Crypto 量化交易

## 架构

```
Python 回测引擎 (自建)  →  Crypto 项目 (因子研发+验证+决策)  →  Obsidian (知识沉淀)
                                   ↓
                    GitHub Actions (每 4h 信号+纸面交易)  →  Telegram 通知
```

- **回测**: `backtests/adx_adaptive_perp_eth_4h.py` — 自建引擎，bar-by-bar，含 _preflight + _run_sanity
- **分析**: 假设检验（p 值+效应量+置信区间）、因子开发、参数决策
- **监控**: GitHub Actions 定时信号检查 + 纸面交易跟踪，Telegram 实时推送
- **Obsidian**: 知识沉淀
- 全部因子自建，零外部依赖

## 技术栈

Python 3.12 + pandas + numpy + scikit-learn + PyTorch。交易所 CCXT (Binance)。数据 CSV。

## 项目结构

```
backtests/     ← 策略回测脚本（一个策略一个文件）
tools/         ← 数据拉取、质量检查、验证、因子挖掘、信号脚本
strategies/    ← 可复用的因子/策略模块
data/          ← 市场数据 CSV
loop/          ← 回测循环：tasks.json（任务队列）、findings.md（发现记录）、results/（报告输出）
paper_trade/   ← 纸面交易状态（state.json, trades.csv, equity.csv）
```

## 监控与部署

**GitHub Actions** `.github/workflows/signal_check.yml`：
- 触发：每 4h (`0 */4 * * *`) + 手动 `workflow_dispatch`
- 流程：`fetch_latest.py` → `manual_signal.py` → `paper_trade.py` → Telegram → 状态回写 git
- 通知内容：信号（方向/入场/止损/仓位）+ 纸面交易（入场价/止损/浮盈/权益/回撤/仓位大小）
- 状态持久化：`paper_trade/` 目录由 CI 自动 commit+push，跨运行保持仓位连续性
- 交易所 fallback：OKX → KuCoin → Bybit → Binance（GitHub Actions IP 常被墙）

## 交易所约定

- **交易所**: Binance（所有策略默认 Binance）
- **产品**: USDT-M 永续合约（永续策略默认 USDT-M）

### 费用常量（所有策略统一引用）

**永续策略必须从 `utils/constants.py` 导入，禁止手写。** 关键的约定：

| 常量 | 值 | 说明 |
|---|---|---|
| `FEE_TAKER` | 0.0005 (0.05%) | Binance USDT-M VIP 0 taker **（通用）** |
| `FEE_MAKER` | 0.0002 (0.02%) | Binance USDT-M VIP 0 maker **（通用）** |
| `FEE_SPOT` | 0.001 (0.1%) | 现货策略 **（通用）** |
| `FUNDING_RATE_4H_ETH` | 0.00006531 (0.00653%/4h) | ETH 实测 6.5 年均值 **（ETH 专用）** |
| `SLIPPAGE_ETH` | 0.0002 (0.02%) | ETH 高流动性 **（ETH 专用）** |

**铁律：**
- 必须使用 per-pair 命名（`FUNDING_RATE_4H_ETH` 而不是 `FUNDING_RATE_4H`）——没有"通用默认值"
- 新币种必须先跑 `tools/fetch_funding_rate.py --symbol XXX/USDT:USDT` 校准
- 任何永续策略不得手写 FEE/FUNDING_RATE/SLIPPAGE，必须从 `constants.py` 导入
- 实盘部署时费用与回测必须一致

## 参考

| 位置 | 内容 |
|---|---|
| `lessons-crypto.md` | 经验教训（工作缓冲区，上限 20 条） |
| `crypto-strategy-adx-perp.md` | 主力策略状态与指标 |
| `loop/tasks.json` | 待办任务队列 |
| Obsidian | 长期知识存储（`记忆/场景/` L2） |

# Crypto 量化交易

**策略:** ETH 4H ADX 自适应永续（Donchian 突破 + ADX 体制切换 + ATR% 止损）
**标的:** ETH/USDT 永续 (Binance)
**环境:** `~/.will/venvs/tools/bin/python`
**CI:** GitHub Actions 每 4h（`0 */4 * * *`）→ Telegram 通知

## 架构

```
Python 回测引擎 (自建)  →  Crypto 项目 (因子研发+验证+决策)  →  Obsidian (知识沉淀)
                                   ↓
                    GitHub Actions (每 4h 信号+纸面交易)  →  Telegram 通知
```

- **回测**: `backtests/adx_adaptive_perp_eth_4h.py` — 自建引擎，bar-by-bar，含 _preflight + _run_sanity
- **分析**: 假设检验、因子开发、参数决策
- **监控**: GitHub Actions 定时信号检查 + 纸面交易跟踪，Telegram 实时推送
- 全部因子自建

## 项目结构

```
backtests/     ← 策略回测脚本（一个策略一个文件）
tools/         ← 数据拉取、质量检查、验证、因子挖掘、信号脚本
strategies/    ← 可复用的因子/策略模块
data/          ← 市场数据 CSV
loop/          ← 回测循环：tasks.json（任务队列）、findings.md（发现记录）、results/（报告输出）
paper_trade/   ← 纸面交易状态（state.json, trades.csv, equity.csv）
```

## 子规则文件

`.claude/rules/` 目录包含自动生效的规则：

| 文件 | 触发条件 |
|------|------|
| `backtest-safety.md` | 涉及回测代码 |
| `hypothesis-testing.md` | 涉及策略比较、因子验证 |
| `live-trading-discipline.md` | 涉及策略上线、实盘运行 |
| `strategy-validation.md` | 涉及新策略开发 |

## 监控与部署

**GitHub Actions** `.github/workflows/signal_check.yml`：
- 触发：每 4h + 手动 `workflow_dispatch`
- 流程：`fetch_latest.py` → `manual_signal.py` → `paper_trade.py` → Telegram → 状态回写 git
- 交易所 fallback：OKX → KuCoin → Bybit → Binance

## 费用常量

永续策略必须从 `utils/constants.py` 导入：

| 常量 | 值 | 说明 |
|---|---|---|
| `FEE_TAKER` | 0.0005 (0.05%) | Binance USDT-M VIP 0 taker |
| `FEE_MAKER` | 0.0002 (0.02%) | Binance USDT-M VIP 0 maker |
| `FUNDING_RATE_4H_ETH` | 0.00006531 (0.00653%/4h) | ETH 实测 6.5 年均值 |
| `SLIPPAGE_ETH` | 0.0002 (0.02%) | ETH 高流动性 |

禁止手写费用常量。新币种必须先跑 `tools/fetch_funding_rate.py` 校准。

## 参考

| 位置 | 内容 |
|---|---|
| `lessons-crypto.md` | 经验教训（工作缓冲区，上限 20 条） |
| `crypto-strategy-adx-perp.md` | 主力策略状态与指标 |
| `loop/tasks.json` | 待办任务队列 |

## Obsidian Vault

- **路径:** `C:\Users\cheah\Obsidian\`
- **全局索引:** `C:\Users\cheah\Obsidian\INDEX.md` — vault 完整规则
- **项目笔记:** `Projects/crypto-strategy-pack.md`
- **架构参考:** `Will/L2-场景/crypto-strategy-pack.md`
- **Session 日志:** `Will/L0-原始/session-*.md`

### 常用操作

| 操作 | 方式 |
|------|------|
| 搜索 vault | `rg "关键词" C:\Users\cheah\Obsidian\ --glob '*.md'` |
| 读项目笔记 | 直接打开 `Projects/crypto-strategy-pack.md` |
| 追加 changelog | `Projects/crypto-strategy-pack.changelog.md` |
| 写 Phase 摘要 | 追加到 `Will/L0-原始/session-YYYY-MM-DD.md`，同时追加 JSONL 索引 |
| 交叉引用 | 写新笔记后检查 `Will/_index.md` 补充回链 |

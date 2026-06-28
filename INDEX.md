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
backtests/     ← 策略回测脚本
tools/         ← 数据拉取、质量检查、验证、信号脚本
strategies/    ← 可复用的因子/策略模块
data/          ← 市场数据 CSV
loop/          ← 回测循环：tasks.json、findings.md、results/
paper_trade/   ← 纸面交易状态（state.json, trades.csv, equity.csv）
.claude/rules/ ← Claude Code 规则（以下策略规则与 .claude/rules/ 同步）
```

## 费用常量

必须从 `utils/constants.py` 导入，禁止手写：

| 常量 | 值 | 说明 |
|---|---|---|
| `FEE_TAKER` | 0.0005 (0.05%) | Binance USDT-M VIP 0 taker |
| `FEE_MAKER` | 0.0002 (0.02%) | Binance USDT-M VIP 0 maker |
| `FUNDING_RATE_4H_ETH` | 0.00006531 (0.00653%/4h) | ETH 实测 6.5 年均值 |
| `SLIPPAGE_ETH` | 0.0002 (0.02%) | ETH 高流动性 |

禁止手写费用常量。新币种必须先跑 `tools/fetch_funding_rate.py` 校准。per-pair 命名，无通用默认值。

## 监控与部署

**GitHub Actions** `.github/workflows/signal_check.yml`：
- 触发：每 4h + 手动 `workflow_dispatch`
- 流程：`fetch_latest.py` → `manual_signal.py` → `paper_trade.py` → Telegram → 状态回写 git
- 交易所 fallback：OKX → KuCoin → Bybit → Binance

## 回测安全规则

### 杜绝未来函数

每个 `run_backtest()` 入口必须调用 `_preflight(df)`，检查：
- 信号列和指标列存在
- DatetimeIndex 严格单调递增、无重复
- 预热期后信号列零 NaN
- 信号列类型为布尔/整数（浮点信号可能含未来信息）
- OHLC 逻辑一致性

信号计算每条赋值必须满足：`shift(N)` (N≥1)、`.diff()`、`.pct_change()`、或 `.rolling(W)` + `shift(1)`。

禁止模式：rolling(N).max() 直接与当前 close 比较、fillna 用全局统计量、当前 bar 的 high/low 决定当前 bar 突破信号。

### Sanity Test

每个回测必须执行 `_run_sanity(df)`：
- 强制单一入场持有至结束 → trade PnL = 价格变化减成本
- 全部信号关闭 → 零交易、零收益
- 固定时间点单笔交易 → PnL 与手动计算一致

不通过 → 回测结果无效。

### 数据分割

训练/验证/测试按时间顺序分割，禁止随机。样本外 ≥ 总时长 20%。参数优化后必须在独立样本外验证。

### 费用和滑点

回测必须计入全部交易成本：手续费（maker/taker）、滑点、冲击成本、资金费率。每次报告显式声明费用参数。费用变动视为策略变更。

## 假设检验

### 检验选择

| 场景 | 检验 |
|------|------|
| 策略 A vs B 胜率 | Z-test 双比例 |
| 策略 A vs B 收益率/夏普 | Welch t-test |
| 多策略分类 | χ² |
| 单策略 vs 基准值 | 单样本 t-test |

n < 30 且未验证正态性 → Mann-Whitney U。重尾分布 → log 变换或 trimmed mean。

### 效应量

Cohen's d（均值）：< 0.2 可忽略，0.2-0.5 小，0.5-0.8 中，> 0.8 大。Cohen's h（比例同理）。

### 决策框架

| p 值 | 效应量 | 决策 |
|------|--------|------|
| < α | 中/大 | ✅ 采纳 |
| < α | 小 | ⚠️ 统计显著但实际不值——搁置 |
| ≥ α | — | 🔁 功效不足则延长时间；否则 ❌ 放弃 |

先问"效应量值得在意吗？"——不，显著也别用。

### 多重比较

同时测 > 3 个指标 → Bonferroni 校正（α / N）。或预注册核心指标，其他标明探索性。

### 输出规范

每个检验报告：**结论**（一句话 + p/d/CI）、**数据**（观测值）、**实际意义**、**行动**（采纳/搁置/延长时间/放弃）。标注置信度：🟢 已验证 / 🟡 可能 / 🔴 不确定。

## 策略验证管线

新策略逐阶段通过，每阶段 git commit：

| Phase | 内容 | 门禁 |
|---|---|---|
| 0. 数据 | CCXT 拉取 + DQS | 行数 ≥ 5000, DQS ≥ 85 |
| 1. 因子 IC | ≥3 因子 × ≥3 参数 | IC/ICIR/p/效应量全部报告 |
| 2. 策略回测 | 完整回测 | 7 项指标完整，交易 ≥ 10 笔 |
| 3. 参数稳定性 | ≥1 参数 × ≥3 档位 | 全部档位盈利，PF > 1 |
| 4. 样本外 | 时间分割 | 测试期收益 > 0，夏普 ≥ 训练期 50% |
| 5. 蒙特卡洛 | Bootstrap ≥ 1000 次 | P5 收益 > 0 |
| 6. 极端行情 | ≥3 崩盘窗口 | 强平/最大回撤报告 |
| 7. 跨币 | ≥1 其他币种 | 同策略验证 |
| 8. 多时框 | ≥1 其他时框 | 同策略验证 |

**通过**（全部满足→✅）：样本外收益为正 + 全部门禁通过 + 无 fatal 缺陷。
**改进**（满足任一→🔁）：样本外夏普/回撤明显弱于样本内、显著未跑赢基准、参数不稳定。
**放弃**（满足任一→❌）：样本外收益为负、交易次数 < 10、3 次改进无实质提升。

## 实盘纪律

| # | 规则 |
|---|------|
| 1 | 杜绝未来函数 — _preflight 入口强制检查 |
| 2 | 严防过拟合 — 参数必须样本外+敏感性分析 |
| 3 | 计入真实成本 — 滑点/手续费/冲击成本/资金费率 |
| 4 | 数据一致 — 实盘复权/清洗与回测完全一致 |
| 5 | 环境高可用 — 断网断电自动恢复 |
| 6 | 硬性风控 — 仓位上限/回撤熔断写死在代码中 |
| 7 | 实时异常监控 — 心跳/成交率/滑点/净值报警 |
| 8 | 严禁人工干预 — 回撤在历史范围内不得手动关停/改策略/选择性跟单 |
| 9 | 识别结构变化 — 回撤突破历史极值或市场规则改变时暂停重新评估 |

唯一允许人工介入：代码熔断/强平触发。

## 参数优化纪律

- 一次一变：每次实验只改一个变量
- 评估器不可变：禁止修改回测评估器
- 升级节奏：低垂果实 → 系统性探索 → 结构性改动 → 激进实验。当前阶段无显著提升才升级
- 5 次连续 crash → 暂停告警
- 每 10 轮复盘找规律
- 简洁优于复杂：小提升引入丑陋复杂度 → 不值

## 回测报告完整性

每个回测结果包含：数据范围和时间粒度、总收益/年化收益/最大回撤、夏普比率/卡玛比率、交易次数和胜率、对比基准表现。

## 结果沉淀

回测结果或参数变更后同步更新：

| 目标 | 内容 |
|------|------|
| `crypto-strategy-adx-perp.md` | 关键指标、验证状态、已知限制 |
| `loop/findings.md` | 追加发现条目 |
| `lessons-crypto.md` | 新教训（上限 20 条→归档到 Obsidian） |

## 参考

| 位置 | 内容 |
|---|---|
| `lessons-crypto.md` | 经验教训（上限 20 条） |
| `crypto-strategy-adx-perp.md` | 主力策略状态与指标 |
| `loop/tasks.json` | 待办任务队列 |

## Obsidian Vault

- **路径:** `C:\Users\cheah\Obsidian\`
- **全局索引:** `C:\Users\cheah\Obsidian-Vault\INDEX.md` — vault 完整规则
- **项目笔记:** `Projects/crypto-strategy-pack.md`
- **架构参考:** `Will/L2-场景/crypto-strategy-pack.md`
- **Session 日志:** `Will/L0-原始/session-*.md`

### 常用操作

| 操作 | 方式 |
|------|------|
| 搜索 vault | `rg "关键词" C:\Users\cheah\Obsidian-Vault\ --glob '*.md'` |
| 读项目笔记 | 直接打开 `Projects/crypto-strategy-pack.md` |
| 追加 changelog | `Projects/crypto-strategy-pack.changelog.md` |
| 写 Phase 摘要 | 追加到 `Will/L0-原始/session-YYYY-MM-DD.md`，同时追加 JSONL 索引 |
| 交叉引用 | 写新笔记后检查 `Will/_index.md` 补充回链 |

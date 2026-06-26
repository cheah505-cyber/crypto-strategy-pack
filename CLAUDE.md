# crypto-strategy-pack — ETH 4H ADX 自适应永续

## 环境

- Python 3.12: `~/.will/venvs/tools/bin/python`
- 依赖: numpy, pandas, ccxt (系统 venv 已有)
- 标的: ETH/USDT 永续 (Binance)
- CI: GitHub Actions 每 4h → Telegram 通知

## 跑法

```bash
cd ~/Projects/crypto-strategy-pack

# 回测
python backtests/adx_adaptive_perp_eth_4h.py

# 数据拉取
python tools/fetch_latest.py

# 信号 + 纸面交易
python tools/manual_signal.py
python tools/paper_trade.py
```

## 项目结构

```
backtests/      策略回测脚本
tools/          数据拉取、质量检查、验证、信号
strategies/     可复用因子/策略模块
data/           市场数据 CSV
loop/           回测循环 (tasks.json, findings.md)
paper_trade/    纸面交易状态 (state.json, trades.csv, equity.csv)
docs/           设计文档
```

## 核心约定

### 杜绝未来函数
- `run_backtest()` 入口必须调 `_preflight(df)`
- 信号计算必须: `shift(N)` (N≥1) / `.diff()` / `.pct_change()` / `.rolling(W)` + `shift(1)`
- 禁止: `rolling(N).max()` 与当前 bar 比较、fillna 用全局统计量

### 费用常量
- 必须从 `utils/constants.py` 导入: `FEE_TAKER`, `FEE_MAKER`, `FUNDING_RATE_4H_ETH`, `SLIPPAGE_ETH`
- 禁止手写费用。新币种必须先跑 `tools/fetch_funding_rate.py`

### 回测安全
- Sanity test: `_run_sanity(df)` — 强制单笔持有 + 零信号验证
- 数据分割: 按时间顺序，样本外 ≥ 20%
- 回测必须计入全部交易成本

### 参数优化
- 一次只改一个变量
- 禁止修改回测评估器
- 5 次连续 crash → 暂停
- 每 10 轮复盘

### 假设检验
- A vs B 胜率: Z-test / 收益率: Welch t-test
- n < 30 → Mann-Whitney U
- 先看效应量（Cohen's d），再看 p 值
- > 3 个指标同时测 → Bonferroni 校正

## 实盘纪律

1. 杜绝未来函数
2. 参数必须样本外验证
3. 计入真实成本（滑点/手续费/资金费率）
4. 硬性风控（仓位上限/回撤熔断）
5. 严禁人工干预（回撤在历史范围 → 不关停/不改策略）
6. 结构变化 → 暂停重新评估

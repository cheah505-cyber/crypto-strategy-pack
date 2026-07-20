# Crypto 量化交易策略

> 自包含的 Windows 项目。任何 Agent 从仓库根目录即可理解策略、运行验证并接管纸面交易状态；不依赖指定插件或 MCP。

## 目录结构

```
crypto-strategy-pack/
├── README.md               ← 本文件：入口说明
├── STRATEGY.md             ← 主力策略完整定义（ADX 自适应永续）
├── FACTORS.md              ← 因子定义（动量、趋势、波动率）
├── PARAMETERS.md           ← 参数表、费用常量、交易所约定
├── VALIDATION.md           ← 8 阶段验证管线 + 假设检验标准
├── DISCIPLINE.md           ← 交易纪律 10 条 + 人工干预规则
├── LESSONS.md              ← 经验教训（论证阶段总结 + 实盘阶段）
├── ARCHITECTURE.md         ← 整体架构：数据→回测→信号→交易→CI
├── FINDINGS.md             ← 回测发现结论汇总
├── backtests/              ← 回测脚本
├── tools/                  ← 数据拉取、信号和验证工具
├── strategies/             ← 因子/策略模块
├── utils/                  ← 常量与共享工具
├── data/                   ← 市场数据 CSV
├── paper_trade/            ← 纸面交易状态
├── loop/                   ← Agent 回测任务队列
└── .github/workflows/      ← GitHub Actions 自动纸面交易
```

## 使用方式

给 AI agent 时只说："读 README.md，这是 crypto 量化交易策略包，帮我理解后可以执行回测。"

### 恢复运行

```powershell
# 1. 在 Windows PowerShell 中进入项目
Set-Location C:\Users\cheah\Projects\crypto-strategy-pack

# 2. 创建项目虚拟环境并安装运行依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 研究脚本需要时再安装（可选，依赖较大）
.\.venv\Scripts\python.exe -m pip install -r requirements-research.txt

# 3. 拉取数据（如果需要）
.\.venv\Scripts\python.exe tools\fetch_ohlcv.py --symbol ETH/USDT --timeframe 4h

# 4. 跑回测
.\.venv\Scripts\python.exe backtests\adx_adaptive_perp_eth_4h.py

# 5. 部署 CI 时设置 GitHub Secrets
# 见 ARCHITECTURE.md 的 CI/CD 章节
```

## 核心策略速览

- **策略**: ADX 自适应永续 ETH 4H
- **标的**: ETH/USDT 永续合约 (Binance)
- **时框**: 4h
- **类型**: 趋势跟踪（Donchian 突破 + ADX 体制切换）
- **当前 4H 数据**: 从 2023-01 开始，末端由 CI 持续追加
- **历史全周期冻结结果**: 2019-01 → 2026-05；Sharpe 1.30、收益 +1,649%、DD -38.2%、0 爆仓
- **当前状态**: 纸面交易运行中（GitHub Actions 每 4h）；实时权益、仓位、回撤和交易数以 `paper_trade/state.json` 与 CSV 台账为准
- **Agent 接管**: 先读 `AGENTS.md` 与 `INDEX.md`

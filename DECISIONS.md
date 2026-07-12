# 设计决策与上线条件

## 已确认架构

- 主策略：ETH/USDT 永续 4H，Donchian 突破 + ADX 体制切换 + ATR% 止损。
- ADX 用于区分趋势/震荡；体制切换后的参数必须逐段 walk-forward 验证。
- ATR / close × 100 用作无量纲风险基准，跨标的应用前仍须重新校准。
- 所有回测入口执行 `_preflight` 与 `_run_sanity`。

## 已验证拒绝

完整实验与指标见 `STRATEGY.md`、`FINDINGS.md` 和 `loop/findings.md`。不得仅因短期 paper trade 表现重新启用已拒绝改动。

## 已知缺陷

- 开发早期部分参数选择过程没有完整记录，无法事后补造证据。
- 主线仅部署 ETH/USDT；BTC 有过回测探索但未形成持续验证与部署结论。
- paper trade 样本仍小，不能据此判断策略已稳定复制回测表现。
- 回撤可能超过历史回测区间；需要用状态文件和冻结回测基准持续比较。
- 旧记录引用的“2026-06-06 论证阶段 20 条经验”源文件已不存在；已恢复部分见 `docs/knowledge/lessons-archive-2026.md`，其余不可恢复且不得补造。

## Paper trade → 实盘条件

只有以下条件同时满足时，才可提出小仓实盘评审；不能自动切换：

1. paper trade 至少完成 30 笔可核验交易。
2. 最大回撤保持在已验证历史范围内，或超出部分已有独立原因和重新验证。
3. 交易成本、资金费率、滑点和数据处理与回测一致。
4. GitHub Actions、状态持久化、Telegram 和故障恢复持续稳定。
5. 没有未来函数、状态错序、重复执行或信号/成交不一致。
6. 用户明确批准实盘；密钥、仓位上限和熔断另行审查。

## 暂停与重新评估

出现任一情况时暂停升级实盘，不得临时调参追损：

- 回撤突破历史极值且不是单次可解释异常。
- 数据源、合约规则、费用或资金费率结构改变。
- signal 与 paper trade 使用不同状态或同一 bar 重复执行。
- 连续运行结果显著偏离 walk-forward 预期。
- preflight、sanity、状态完整性或 CI 检查失败。

## CI 决策

- 正确顺序：`fetch_latest → paper_trade → manual_signal → commit state → Telegram`。
- `manual_signal` 必须读取本轮更新后的 `state.json`。
- workflow 必须使用 concurrency，避免定时与手动任务重叠。
- 2026-06-24 曾发现旧状态导致信号与 paper trade 矛盾，并发现重复推送风险；此规则是回归门禁。

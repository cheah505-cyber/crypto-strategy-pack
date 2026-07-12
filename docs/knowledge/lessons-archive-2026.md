# 2026 量化经验归档

## 从现存项目笔记恢复

以下内容在 2026-07-12 自包含审计时，从仍存在的项目笔记交叉恢复：

1. 体制切换的关键不是 ADX 指标本身，而是不同体制参数必须逐段 walk-forward 独立验证。
2. ATR / close × 100 可作为无量纲风险基准；跨币种应用仍须分别校准费用、波动与流动性。
3. 所有回测入口必须执行 preflight 和 Hold-to-end、Zero-signal、Fixed-trade 三项 sanity。
4. paper trade 至少 30 笔且回撤保持在验证范围内，才可提出小仓实盘评审。
5. 已验证拒绝的改进不能因短期 paper trade 波动随意重新启用。
6. signal 必须在 paper trade 更新状态后生成，且 CI 需要 concurrency 防止重复推送。

## 无法恢复的历史

`lessons-crypto.md` 曾引用一份“2026-06-06 论证阶段 20 条经验”外部文件。审计时该文件在现有目录中不存在，因此无法完整迁移；缺失内容不做推测或补造。现存可验证规则以 `LESSONS.md`、`DECISIONS.md`、`FINDINGS.md` 和本文件为准。

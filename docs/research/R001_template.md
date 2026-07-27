## Research ID
R{三位数字}_{简短英文描述}

---

## Background
<!-- 当前策略的现状、为什么提出这个研究 -->

---

## Current Rule
<!-- 当前规则的完整描述（精确到参数值） -->

---

## Research Question
<!-- 用问句形式精确描述要研究的问题 -->

---

## Hypothesis
<!-- 假设的核心内容 -->

---

## Acceptance Criteria

> ⚠️ **此字段必须先于 Result 写入，且写入后禁止修改。**
> research_runner.py 会自动检查：如果 Acceptance Criteria 的确定时间
> 晚于或等于 Result 的写入时间，报告将被标记为 INVALID。

### 判定标准
<!-- 必须具体到可直接套用的统计标准。
     不合格示例："达到统计要求"
     合格示例：
     "双样本 t 检验，p < 0.05；每组样本量不少于30笔；
     分别在2023/2024/2025三个完整年度单独检验，
     三年中至少2年同时满足上述显著性条件。" -->

### 样本要求
<!-- 最低样本量、时间段覆盖等 -->

---

## Dataset
<!-- 使用的数据范围、来源、时间跨度 -->

---

## Evaluation Metrics
<!-- 衡量指标（胜率、盈亏比、最大回撤等） -->

---

## Method
<!-- 分析方法和步骤 -->

---

## Result
<!-- 分析结果（由 research_runner.py 或人工填写） -->

---

## Conclusion
<!-- 研究结论 -->

---

## Decision
<!-- 只能是 Accepted / Rejected / Need More Data -->

---

## Status
<!-- 只能是 Planning / Running / Completed / Rejected / Implemented -->

---

## Timestamps

| 事件 | 时间 |
|------|------|
| Acceptance Criteria 确定 | YYYY-MM-DD HH:MM |
| Result 写入 | YYYY-MM-DD HH:MM |
| 报告生成 | YYYY-MM-DD HH:MM |

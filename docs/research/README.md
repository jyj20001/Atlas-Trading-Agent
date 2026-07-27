# Research Framework — 策略研究流程说明

## 定位

本框架是 Atlas Trading Agent 的策略研究基础设施，不属于生产代码。
所有涉及 Buy Stop 参数、评分权重、风控规则的修改，必须先走完
完整的 Research → Backtest → Walk Forward → Review 流程。

---

## 完整流程

```
Hypothesis（提出假设）
    ↓
Research（立项 → 写 R00X 文档）
    ↓
Data Preparation（复制生产快照到 research/data/）
    ↓
Run Research Script（research_runner.py 执行分析）
    ↓
Evaluation（对照 Acceptance Criteria 判定）
    ↓
Decision（机械判定：Accepted / Rejected / Need More Data）
    ↓
Backtest（用 Historical Snapshot Layer 做回测）
    ↓
Walk Forward（样本外测试）
    ↓
Review ──→ 仅项目负责人（人工）可以批准
    ↓
Implemented（应用到生产代码）
```

---

## 关键阶段说明

### 1. Research — 立项
- 创建 `R{三位数字}_{英文描述}.md`，填写全部字段
- **Acceptance Criteria 必须先于 Result 写入，且写入后不能修改**
- Status = Planning

### 2. Run — 执行分析
- `research_runner.py R002` 自动执行
- 运行前检查：
  - Acceptance Criteria 不为空 → 否则拒绝执行
  - 脚本不直连生产 DB → 否则拒绝执行
- 运行后检查：
  - Acceptance Criteria 确定时间 < Result 写入时间 → 否则报告标记为 INVALID

### 3. Decision — 机械判定
- 由 Acceptance Criteria 的检验结果自动判定，不需要人工介入
- 三类输出：Accepted / Rejected / Need More Data
- 写入 `R00X.md` 的 Decision 和 Status 字段

### 4. Review — 人工审批

> ⚠️ **权限说明**
>
| 角色 | 可以做什么 | 不可以做什么 |
|------|-----------|-------------|
| Hermes (AI Agent) | 把 Status 推进到 "待Review" | 不能自行将 Status 标记为 "已通过Review" 或 "Implemented" |
| 项目负责人 (人工) | 批准/拒绝/要求补充数据 | — |

Decision 字段可以由 Hermes 根据 Acceptance Criteria 的检验结果自动写入，
因为标准已经提前锁定，判定是机械的。但 Status 进入 "Implemented" 之前，
必须经过 Backtest → Walk Forward → Review 三步，其中 Review 这一步
只能由项目负责人（人工）确认。

### 5. Implemented — 应用到生产
- 只有经过 Review 批准的研究才能进入此阶段
- 修改生产代码后，同步更新 CHANGELOG.md

---

## 新增研究流程（R003, R004, ...）

1. 复制 `R001_template.md` 为 `R003_xxx.md`
2. 按模板规范填写所有字段（Acceptance Criteria 必须具体到统计阈值）
3. 在 `research/` 目录下创建对应的分析脚本 `R003_xxx.py`
4. 从生产库复制数据快照到 `research/data/`
5. 运行 `research_runner.py R003`
6. 按 Decision 结果推进

不需要修改 `research_runner.py` 本身——它按 R00X 编号自动发现脚本和文档。

# Atlas Trading Agent — 任务列表

> 当前状态追踪。已完成 ✅、进行中 🔄、未来计划 📋、已暂停 ⏸️、已归档 🗄️。

---

## ✅ 已完成

### Buy Stop V3.4 Production
- [x] 核心 Buy Stop 筛选引擎（130分五维评分体系）
- [x] 行情数据获取（腾讯K线 + 新浪股票列表）
- [x] 基本面数据获取（巨潮资讯公告）
- [x] 突破生命周期识别（EARLY/TRENDING/EXTENDED/CLIMAX）
- [x] 市场环境评分（三大指数加权）
- [x] 板块强度评分（30+行业板块超额收益）
- [x] 全市场批量扫描引擎（异常隔离）
- [x] 预过滤模块（减少无效请求）
- [x] 报告生成（JSON + Markdown + CSV）
- [x] 企业微信推送（A+ 级通知）
- [x] 日志系统（按日轮换，保留30天）
- [x] 53 项测试覆盖全部核心模块
- [x] curl 子进程 HTTP 客户端（规避 SSL 问题）

### Alibaba Risk Monitor V3.0
- [x] 法律案件监控（PACER docket）
- [x] 政策新闻监控（关键词过滤，只推送高影响事件）
- [x] 价格/成交量异常监控
- [x] 企业微信推送告警
- [x] cron 定时任务（价格 15min + 综合 30min）

### 数据层升级 (v3.5)
- [x] SQLite 市场数据库（database.py）
  - [x] 自动建表 / 缓存写入 / 增量更新
  - [x] 4467 只全市场缓存完成
  - [x] 缓存命中后 1000 只仅 10.4 秒
- [x] 信号历史数据库（signal_database.py）
  - [x] 候选信号自动存储
  - [x] 按日期/代码查询
  - [x] 价格字段预留（5/10/20日后）
- [x] 双数据源路由（主板→腾讯主域，科创板→腾讯备用域）
- [x] WAF 检测和非 JSON 响应安全处理

### 工程标准化
- [x] 项目标准化目录结构
- [x] README.md（完整版）
- [x] AGENT.md（AI Agent 人格文件）
- [x] MEMORY.md（项目状态恢复）
- [x] TASKS.md（任务列表）
- [x] CHANGELOG.md（版本历史）
- [x] LICENSE（MIT）
- [x] requirements.txt（依赖管理）
- [x] .gitignore（敏感文件排除）
- [x] 工程体检报告（docs/code_audit.md）
- [x] 长期开发规范（docs/development_workflow.md）

---

## 🔄 进行中

### 生产观察 (Production Observation Phase)
- [ ] **30 个交易日观察期** — 2026-07-24 起
  - [ ] 每日全市场扫描
  - [ ] 监控数据源稳定性
  - [ ] 监控 SQLite 缓存性能
  - [ ] 记录候选信号
  - [ ] 观察期内原则上不开发新功能
  - [ ] 只允许 bug 修复和稳定性优化

---

## 🗄️ Future Roadmap（暂不开发）

以下功能已确认价值，但当前处于 Production Observation Phase，暂不开发。
待观察期结束且获项目负责人批准后方可启动。

### Market Score → Market Gate（暂不开发）
- 现状：Market Score 是 0~5 分的评分维度，实际权重低
- 设想：将 Market Score 升级为 Market Gate——熊市硬性开关，不满足条件直接不让任何 Buy Stop 信号通过
- 暂不开发原因：当前熊市判断逻辑简单（MA20/Ma50），需要更多真实数据验证后再决定是否做硬性 gate
- 约束：
  - 不能降低现有 130 分体系兼容性
  - Gate 开关必须是可配置的
  - Gate 参数必须经过回测验证

### Sector Stage（暂不开发）
- 现状：Sector Score 是 0~10 分的评分维度，仅计算 5 日超额收益
- 设想：为板块增加阶段识别——板块处于早期/扩散/高潮/衰退阶段，结合个股阶段联合判断
- 暂不开发原因：需要先建立板块指数历史数据库，当前腾讯 API 仅提供单只股票 K 线，板块指数获取尚未稳定
- 约束：
  - 不能增加额外的 API 依赖
  - 板块历史数据必须全部缓存到 SQLite

### Historical Fundamental Snapshot（Backtest 专用，暂不开发）
- 现状：回测中的基本面评分每次都实时查询巨潮资讯（未来函数风险）
- 设想：建立历史基本面快照数据库，按日期存储每条公告的快照，回测时按当日可获取的数据查询
- 暂不开发原因：当前回测模块已暂停，基本面数据量大且需要历史日期重建，开发成本高
- 约束：
  - 每条公告必须带发布日期
  - 查询时必须按 signal_date 过滤：announcement_date <= signal_date
  - 不能有 Look-ahead Bias

### Historical Snapshot Layer（高优先级，Backtest 前置条件）
| 属性 | 值 |
|------|------|
| **Priority** | High |
| **Dependency** | 必须先于任何 Backtest 开发 |
| **Status** | Pending（等待 Production Observation Phase 结束后评估） |

**目的：**
彻底避免历史回测中的 Look-ahead Bias（未来函数）。

**包含模块：**

| 子模块 | 用途 | 数据量预估 |
|--------|------|:---------:|
| □ Historical Announcement Snapshot | 公告历史快照（业绩预告/快报/合同/回购） | 每年 ~10 万条 |
| □ Historical Fundamental Snapshot | 基本面指标历史（营收/利润/ROE 等） | 每年 ~5 万条 |
| □ Historical Sector Snapshot | 板块指数成分股历史（用于板块强度评分回测） | 每年 ~3 万条 |
| □ Historical Market Snapshot | 市场环境历史（三大指数 K 线历史快照） | 每年 ~750 根 |

**开发顺序（必须遵守）：**

1. 设计数据表结构（SQLite，带 publish_date 字段）
2. 写数据抓取脚本（按日期爬取历史公告/指数数据）
3. 写数据验证脚本（随机抽样验证历史日期数据正确性）
4. 写回测查询接口（query_as_of(date) 返回截至该日期的数据快照）
5. 集成到 BacktestEngine

**验证标准：**
- 对于任意历史日期 T，`query_as_of(T)` 返回的数据必须与 T 日实际可获取的数据一致
- 随机抽取 10 个历史日期，人工验证数据准确性
- 所有验证通过后，才能用于实际回测

---

## ⏸️ 暂停开发

### 回测扩展
- [x] A/B/C/D 四种配置对比回测
- [x] 交易成本计算（佣金+印花税+滑点）
- [x] 止损/止盈/超时三种退出
- [x] 评分分组统计
- [ ] ~~多周期回测~~ — 已暂停，当前回测功能已满足需求
- [ ] ~~回测结果可视化~~ — 已暂停，价值有限
- [ ] ~~机器学习参数优化~~ — 已暂停，过拟合风险高

**暂停原因：** 回测仅供参考，不能预测未来。当前功能已能验证策略有效性。过度回测可能导致过拟合。

### Buy Stop 规则调整
- [ ] ~~新增评分维度~~ — 已暂停，130 分体系已足够
- [ ] ~~参数优化~~ — 已暂停，当前参数经过验证

**暂停原因：** Buy Stop V3.5 已进入 Production Observation Phase。任何策略参数修改需要 30 交易日观察数据支持。

---

## 📊 项目健康度

| 指标 | 状态 |
|------|------|
| 核心模块测试覆盖率 | ✅ >80% |
| 生产运行稳定性 | ✅ 稳定（异常隔离） |
| 数据源可用性 | ✅ 腾讯/新浪/巨潮全部可用 |
| 企业微信推送 | ✅ 配置即用 |
| cron 定时任务 | ✅ 正常运行 |
| 日志系统 | ✅ 按日轮换 |
| SQLite 缓存 | ✅ 4467 只全缓存，0.01秒/只 |
| 代码风格 | ⚠️ 部分文件需 ruff 格式化 |
| 文档完整性 | ✅ AGENT + MEMORY + README + CHANGELOG + DEVELOPMENT_WORKFLOW 齐全 |

### 长期维护任务

| 任务 | 频率 | 说明 |
|------|:----:|------|
| 运行所有测试 | 每次修改 | `python tests/test_*.py` 确保全部通过 |
| 同步文档 | 每个版本 | MEMORY / TASKS / CHANGELOG / README 同步更新 |
| 创建版本 Tag | 重大功能 | `git tag -a vX.Y-<name> -m "<描述>"` |
| 检查 .gitignore | 新增文件类型 | 确保数据库/日志/输出不会被提交 |
| 检查 CHANGELOG | 每个版本 | 新增/Fix/Optimize 分类清晰 |

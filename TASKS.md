# Atlas Trading Agent — 任务列表

> 当前状态追踪。已完成 ✅、进行中 🔄、未来计划 📋、已暂停 ⏸️、已归档 🗄️。

**Version:** v1.0.0 Stable Baseline
**Stage:** Version Freeze — Published
**Strategy:** Frozen — Buy Stop core sealed

---

## ✅ 已完成

### Buy Stop V3 筛选引擎（策略核心，已冻结）
- [x] 核心 Buy Stop 筛选引擎（130 分五维评分体系）
- [x] 行情数据获取（Provider Chain: Futu → 东方财富 → 腾讯）
- [x] 基本面公告数据获取（巨潮资讯 CNINFO）
- [x] 突破生命周期识别（EARLY/TRENDING/EXTENDED/CLIMAX）
- [x] 市场环境评分（三大指数加权）
- [x] 板块强度评分（30+ 行业板块超额收益）
- [x] 全市场批量扫描引擎（异常隔离）
- [x] 预过滤模块
- [x] 报告生成（JSON + Markdown + CSV）
- [x] 企业微信推送（A+ 级通知）
- [x] 日志系统（按日轮换，保留 30 天）
- [x] SQLite 市场数据库（4467 只全缓存）
- [x] curl 子进程 HTTP 客户端

### Historical Snapshot Layer
- [x] 4 张快照表设计（announcement/fundamental/sector/market）
- [x] `query_*_as_of(signal_date)` 时态查询接口
- [ ] 防未来函数（available_time <= signal_date 强制过滤）
- [x] CNINFO 公告快照采集器（performance_forecast / report / contract / buyback）
- [x] No-lookahead bias 测试（5 项验证）
- [x] 采集器 v2：自动分页 + 月度切片 + 断点续传（11 项测试通过）

### Provider Chain 数据架构
- [x] `data/kline_providers/` 三层架构
- [x] FutuProvider（OpenD 连接，全量历史 2006~2026）
- [x] EastMoneyProvider（HTTP API，全量历史，含 IP 限流处理）
- [x] TencentProvider（640 根 fallback）
- [x] `data/kline_normalizer.py` 统一输出格式
- [x] 数据库优先读取逻辑（`fetch_klines` → DB → Provider fallback）

### PortfolioEngine 组合回测
- [x] 时间驱动组合回测
- [x] T+1 资金管理（CashManager）
- [x] 20% / 5 只仓位限制
- [x] A 股合规回测引擎（EngineV36）
- [x] 组合级指标（复利年化收益/回撤/夏普/Profit Factor）
- [x] 全部测试通过（7/7, 38 assertions）

### 基本面数据基础设施
- [x] `fundamental_snapshot` 表（historical.db）— 东财结构化财务数据
- [x] `data/fundamental/fundamental_collector.py` — 东财数据源采集器
- [x] `scripts/backfill_fundamental.py` — 回填脚本（断点续传）
- [x] `scripts/update_fundamental_daily.py` — 增量更新
- [x] 唯一索引 `(code, fiscal_period, source)` — 防止重复
- [x] 供应商标记 `source='eastmoney'`
- [x] `query_fundamentals_as_of()` 查询接口

### CNINFO Announcement Layer
- [x] `announcement_snapshot` 表已回填 9,000+ 条 / 3,500+ 只
- [x] FundamentalScorer 正式数据源（Zero Network）
- [x] Cron `--fundamental` 已注入生产扫描

### Production Deployment
- [x] Cron 每日全市场扫描（15:40）— `--fundamental` 启用
- [x] Cron 盘前扫描（09:00）— `--fundamental` 启用
- [x] 企业微信推送（Webhook 环境变量注入，不硬编码）
- [x] Final Acceptance Test（7 项全部通过）
- [x] Version Freeze — v1.0.0 Published
- [x] GitHub Release v1.0.0

### Engineering Standardization
- [x] GitHub 推送（`github.com:jyj20001/Atlas-Trading-Agent.git`）
- [x] README / AGENT / MEMORY / TASKS / CHANGELOG
- [x] .gitignore（覆盖 *.db / *.csv / __pycache__ / .env）

---

## 🔄 正在进行

### Futu 全历史 K 线后台补库（持续）
- [ ] 每日配额 ~96 只，预计 ~46 天完成全量 4,467 只
- [ ] 已完成 96 只全量（4800 根/只）

### Fundamental Snapshot 数据续采
- [ ] 后台持续回填（东方财富 API 分批限流）
- [ ] `query_fundamentals_as_of()` 已实现但未被评分模块调用（v1.1 规划）

### Live Validation（持续运行）
- [ ] 连续运行 2~4 周，监控评分稳定性
- [ ] 每日扫描日志自动归档
- [ ] 企业微信推送持续验证

---

## 🗄️ v1.1 Feature Planning（暂停开发）

### 待基本面数据链路修复后
- 将 `fundamental_snapshot` 营收/净利/ROE 数据接入评分（替代或补充现有 15 分）
- `Market Score → Market Gate` 熊市开关
- `Sector Stage` 板块阶段识别
- 多时间框架分析（日线 + 周线 + 60 分钟）
- AI 辅助评分
- 云服务器部署

---

## 项目健康度

| 指标 | 状态 |
|------|:----:|
| 核心模块测试 | ~70 项，全部通过 |
| 生产运行 | ✅ 稳定（异常隔离） |
| 数据源可用性 | ✅ Provider 链多重 fallback |
| 企业微信推送 | ✅ 配置即用（环境变量注入） |
| Cron 定时任务 | ✅ `--fundamental` 启用 |
| SQLite 缓存 | ✅ 4467 只全缓存 |
| Git | ✅ v1.0.0 Published |

# MEMORY.md — Atlas Trading Agent 项目状态记录

> 本文件用于在 AI Agent 新 Session 启动时快速恢复上下文。  
> 新的 Agent 请先读取本文件，再读取 AGENT.md 获取工作原则。

---

## 当前项目状态

**版本:** v1.0.0 Stable Baseline  
**状态:** Version Freeze（版本冻结）  
**最后更新:** 2026-07-26  
**运行频率:** 每日收盘后（15:00 后）通过 cron 自动扫描  
**推送方式:** 企业微信机器人 Webhook  

**当前阶段规则：**
- Buy Stop 策略核心已冻结（screener / 130 分体系 / Buy Stop 参数）
- 允许：数据层扩展 / Bug 修复 / 稳定性优化
- 禁止：修改策略逻辑、评分权重、交易参数

---

## 已完成的模块

### ✅ Buy Stop V3 筛选引擎（策略核心，已冻结）
- **入口:** `run_scan.py`（全市场扫描）/ `run_daily.sh`（cron 包装）
- **核心:** `core/screener.py` — StockScreener 筛选引擎（130分制）
- **扫描引擎:** `scanner/batch_runner.py` — 异常隔离、重试、进度输出
- **股票池:** `scanner/universe.py` — ST/北交所过滤、上市天数判断
- **报告:** `scanner/report.py` — JSON + Markdown + CSV
- **通知:** `utils/notifier.py` — 企业微信（A+ 级推送详情）
- **评分:** 五维评分（技术100 + 基本面15 + 市场5 + 板块10 = 130分）

### ✅ Breakout Stage 生命周期识别
- BreakoutStageIdentifier（core/breakout_stage.py）
- 四阶段: EARLY_BREAKOUT → TRENDING → EXTENDED → CLIMAX

### ✅ 市场环境评分 / 板块强度评分
- MarketRegimeScorer（core/market_regime.py）
- SectorScorer（core/sector_scorer.py）

### ✅ 基本面评分（announcement_snapshot 数据源）
- FundamentalScorer（core/fundamental_scorer.py）
- 业绩预增 / 快报 / 重大合同 / 回购增持
- **当前状态:** ✅ Production Ready
  - 9,000+ 条公告数据（覆盖 3,500+ 只股票）
  - 读取 `announcement_snapshot` 表，Zero Network
  - 支持公告类型: Performance Forecast / Performance Report / Major Contract / Buyback
- **Cron 配置:** `--fundamental` 已注入生产扫描

### ✅ 企业微信推送
- A+ (>=105) 和 A (>=95) 级推送详情
- 无候选时推送通知

### ✅ Provider Chain 数据架构
- `data/kline_providers/` — FutuProvider / EastMoneyProvider / TencentProvider
- 条件导入、三层 fallback
- `data/market_fetcher.py` — 数据库优先读取，Provider 补充

### ✅ Historical Snapshot Layer
- `data/snapshot_schema.py` — 4 张快照表（announcement/fundamental/sector/market）
- `data/snapshot_query.py` — `query_*_as_of(signal_date)` 时态查询接口
- `data/cninfo_snapshot_collector.py` — CNINFO 公告采集

### ✅ PortfolioEngine 组合回测
- `backtest/portfolio_engine.py` — 时间驱动组合回测
- `backtest/cash_manager.py` — T+1 资金管理
- `backtest/engine_v36.py` — A 股合规回测引擎

### ✅ Engineering Standardization & Git v1.0.0
- Git tag v1.0.0 已推送到 GitHub
- GitHub: `github.com:jyj20001/Atlas-Trading-Agent.git`

### ✅ 基本面数据基础设施
- `fundamental_snapshot`（historical.db）— 东方财富结构化财务数据
- `data/fundamental/fundamental_collector.py` — 采集器
- `scripts/backfill_fundamental.py` — 全量回填（支持 --resume 断点续传）
- **已知缺口:** `query_fundamentals_as_of()` 已实现但未被任何评分子系统调用

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 运行时 | Python 3.11+（标准库为主） |
| HTTP | curl 子进程 |
| K线数据库 | SQLite（日均缓存 4467 只） |
| Provider 链 | Futu OpenAPI → 东方财富 → 腾讯（三层 fallback） |
| 历史快照 | historical.db（4 张时态表） |
| 通知 | 企业微信机器人 Webhook |
| 部署 | macOS / Linux + crontab |

---

## 已知的局限性

1. **东方财富 IP 限流** — A 股全量回填需分批（每批 ~100 只），非一次性完成
2. **Futu OpenD 每日配额限制** — 历史 K 线回填受 100 次/日 限制
3. **数据源依赖** — 腾讯/新浪/巨潮 API 可能随时变更
4. **A 股 T+1** — 当日买入不可卖出
5. **北交所不支持** — 故意排除
6. **仅做扫描，不自动下单**

---

## 项目健康度

| 指标 | 状态 |
|------|:----:|
| 测试套件 | ~70 项 |
| 核心模块测试 | ✅ 全部通过 |
| 生产运行 | ✅ 稳定（异常隔离） |
| 企业微信推送 | ✅ 配置即用 |
| cron 定时任务 | ✅ 正常运行 |
| SQLite 缓存 | ✅ 4467 只全缓存 |
| 文档 | ⚠️ AGENT/MEMORY/README/CHANGELOG 齐全，工程 doc 需补充 |


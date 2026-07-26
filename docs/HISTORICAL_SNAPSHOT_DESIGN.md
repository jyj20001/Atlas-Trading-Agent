# Historical Snapshot Layer — 设计方案

**版本:** v3.5.1
**日期:** 2026-07-25
**状态:** 设计稿（待确认后实施）

---

## 1. 问题定义

### 当前问题

回测引擎 (`backtest/engine.py`) 在 `run_single()` 中调用 `StockScreener.evaluate()`，后者使用**实时**巨潮资讯 API 获取公告数据。当回测日期 T（如 2023-06-01）时，引擎仍在读取**今天**的公告数据，导致：

```
Signal Date: 2023-06-01
Used Data:   2026-07-25 的公告（包含 2023-06-02 之后发布的）
→ Look-ahead Bias ✓
```

### 影响范围

| 评分模块 | 数据源 | 未来函数风险 |
|----------|--------|:-----------:|
| `FundamentalScorer._score_forecast()` | CNINFO 实时 API | 🔴 高 |
| `FundamentalScorer._score_report()` | CNINFO 实时 API | 🔴 高 |
| `FundamentalScorer._score_major_contract()` | CNINFO 实时 API | 🔴 高 |
| `FundamentalScorer._score_buyback()` | CNINFO 实时 API | 🔴 高 |
| `SectorScorer._get_index_return()` | 腾讯实时 API | 🟡 中 |
| `MarketRegimeScorer.fetch_index_klines()` | 腾讯实时 API | 🟡 中 |

### 核心原则

> `query_as_of(T)` 返回的数据必须与 T 日实际可获取的数据一致。

---

## 2. 架构概述

### 2.1 数据库

**独立数据库文件:** `data/historical.db`

独立于 `market.db` 的原因：
- 职责分离：market.db 是 K 线缓存，historical.db 是历史快照
- 生命周期不同：market.db 可随时重建，historical.db 一旦建立不应该被覆盖
- 备份策略不同：historical.db 需归档保留

### 2.2 数据流

```
┌──────────────────────────────────────────────────────────┐
│                    daily_snapshot_collector.py             │
│  (每日收盘后自动运行 / 或一次性历史回填)                    │
├──────────────────────────────────────────────────────────┤
│  公告爬虫 ──→ CNINFO API ──→ announcement_snapshot        │
│  财报爬虫 ──→ CNINFO API ──→ fundamental_snapshot          │
│  板块爬虫 ──→ 腾讯 API    ──→ sector_snapshot              │
│  指数爬虫 ──→ 腾讯 API    ──→ market_snapshot               │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    snapshot_query.py                       │
│  (回测引擎专用查询接口)                                    │
├──────────────────────────────────────────────────────────┤
│  query_announcements_as_of(date)                          │
│  query_fundamentals_as_of(date)                           │
│  query_sector_as_of(date)                                 │
│  query_market_as_of(date)                                 │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                    BacktestEngineV36                       │
│  (使用 query_as_of 替代实时 API，消除未来函数)               │
└──────────────────────────────────────────────────────────┘
```

### 2.3 available_time 的含义

每条数据记录的 `available_time` 字段定义为：**该信息首次进入公开领域的时间**。

| 数据类型 | available_time 规则 | 示例 |
|----------|-------------------|------|
| 业绩预告 | 公告发布日期 + 1 日（T+1 披露） | 公告 2026-07-24 → available 2026-07-25 |
| 业绩快报 | 公告发布日期 + 1 日 | 同上 |
| 重大合同 | 公告发布日期 + 1 日 | 同上 |
| 回购增持 | 公告发布日期 + 1 日 | 同上 |
| 板块指数日收盘 | 交易日 + 1 日（收盘后才可知） | 2026-07-24 收盘 → available 2026-07-25 |
| 指数日数据 | 交易日 + 1 日 | 同上 |
| 财报数据 | 财报发布日期 + 1 日 | 同上 |

> **为什么 +1 日？** A 股公告在交易时段内也可能发布，但盘后披露的公告只有次日开盘前才被市场消化。保守取 T+1 确保回测时不会用到当日盘后公告。

---

## 3. 数据库 Schema

### 3.1 announcement_snapshot — 公告快照

```sql
CREATE TABLE IF NOT EXISTS announcement_snapshot (
    code            TEXT NOT NULL,          -- 股票代码, e.g. "000977"
    name            TEXT NOT NULL DEFAULT '', -- 股票名称
    announce_date   TEXT NOT NULL,           -- 公告发布日期, e.g. "2026-07-24"
    available_time  TEXT NOT NULL,           -- 数据可用时间 = announce_date + 1日
    announce_type   TEXT NOT NULL,           -- 公告类型: "performance_forecast" / "performance_report" / "major_contract" / "buyback"
    
    -- 业绩预告字段（仅 announce_type='performance_forecast'/'performance_report' 时有效）
    report_type     TEXT DEFAULT '',         -- 预告类型: "预增" / "预减" / "扭亏" / "首亏" / "预警"
    forecast_type   TEXT DEFAULT '',         -- 类别: "业绩预告" / "业绩快报"
    net_profit_lower REAL,                   -- 净利润下限(万元), nullable
    net_profit_upper REAL,                   -- 净利润上限(万元), nullable
    change_pct_lower REAL,                   -- 变动下限(%), nullable
    change_pct_upper REAL,                   -- 变动上限(%), nullable
    
    -- 合同/回购字段（仅 announce_type='major_contract'/'buyback' 时有效）
    title           TEXT DEFAULT '',         -- 公告标题
    keyword         TEXT DEFAULT '',         -- 匹配关键词: "重大合同" / "中标" / "回购" / "增持"
    
    -- 元数据
    source          TEXT DEFAULT 'cninfo',   -- 数据源
    collected_at    TEXT DEFAULT (datetime('now', 'localtime')),  -- 采集时间
    
    PRIMARY KEY (code, available_time, announce_type)
);
CREATE INDEX IF NOT EXISTS idx_announcement_available 
    ON announcement_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_announcement_code_date 
    ON announcement_snapshot(code, available_time);
```

### 3.2 fundamental_snapshot — 基本面指标快照

```sql
CREATE TABLE IF NOT EXISTS fundamental_snapshot (
    code            TEXT NOT NULL,           -- 股票代码
    name            TEXT NOT NULL DEFAULT '',
    fiscal_period   TEXT NOT NULL,           -- 财报所属期, e.g. "2026Q2" / "2026H1" / "2026FY"
    report_date     TEXT NOT NULL,           -- 财报发布日期
    available_time  TEXT NOT NULL,           -- 数据可用时间 = report_date + 1日
    
    -- 利润表
    revenue         REAL,                    -- 营业收入(万元), nullable
    revenue_yoy     REAL,                    -- 营收同比增长(%), nullable
    net_profit      REAL,                    -- 归母净利润(万元), nullable
    net_profit_yoy  REAL,                    -- 净利润同比增长(%), nullable
    
    -- 资产负债表
    total_assets    REAL,                    -- 总资产(万元), nullable
    total_liab      REAL,                    -- 总负债(万元), nullable
    equity          REAL,                    -- 净资产(万元), nullable
    
    -- 盈利能力
    roe             REAL,                    -- ROE(%), nullable
    gross_margin    REAL,                    -- 毛利率(%), nullable
    net_margin      REAL,                    -- 净利率(%), nullable
    
    -- 元数据
    source          TEXT DEFAULT 'cninfo',
    collected_at    TEXT DEFAULT (datetime('now', 'localtime')),
    
    PRIMARY KEY (code, available_time, fiscal_period)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_available 
    ON fundamental_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_fundamental_code_date 
    ON fundamental_snapshot(code, available_time);
```

### 3.3 sector_snapshot — 板块指数快照

```sql
CREATE TABLE IF NOT EXISTS sector_snapshot (
    index_code      TEXT NOT NULL,           -- 板块指数代码, e.g. "sz980017"
    sector_name     TEXT NOT NULL,           -- 板块名称, e.g. "半导体"
    trade_date      TEXT NOT NULL,           -- 交易日
    available_time  TEXT NOT NULL,           -- 数据可用时间 = trade_date + 1日
    
    close           REAL,                    -- 当日收盘价
    return_1d       REAL,                    -- 当日涨跌幅(%)
    return_5d       REAL,                    -- 5日涨跌幅(%)
    volume          REAL,                    -- 成交量
    ma20            REAL,                    -- 20日均线, nullable
    
    PRIMARY KEY (index_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_sector_available 
    ON sector_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_sector_code_date 
    ON sector_snapshot(index_code, available_time);
```

### 3.4 market_snapshot — 市场环境快照

```sql
CREATE TABLE IF NOT EXISTS market_snapshot (
    index_code      TEXT NOT NULL,           -- 指数代码: "000300" / "000001" / "399006"
    index_name      TEXT NOT NULL,           -- 指数名称: "沪深300" / "上证指数" / "创业板指"
    trade_date      TEXT NOT NULL,           -- 交易日
    available_time  TEXT NOT NULL,           -- 数据可用时间 = trade_date + 1日
    
    open            REAL,                    -- 开盘价
    close           REAL,                    -- 收盘价
    high            REAL,                    -- 最高价
    low             REAL,                    -- 最低价
    volume          REAL,                    -- 成交量
    ma20            REAL,                    -- 20日均线
    ma50            REAL,                    -- 50日均线, nullable
    trend_score     INTEGER,                 -- 当日市场评分 (0~5)
    market_status   TEXT,                    -- "bull" / "neutral" / "bear"
    
    PRIMARY KEY (index_code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_market_available 
    ON market_snapshot(available_time);
CREATE INDEX IF NOT EXISTS idx_market_code_date 
    ON market_snapshot(index_code, available_time);
```

---

## 4. 模块设计

### 4.1 文件结构

```
buy_stop_v3/data/
├── database.py           # 现有行情数据库 (market.db)
├── snapshot_schema.py    # NEW — Historical Snapshot 建表 + schema 管理
├── snapshot_collector.py # NEW — 数据采集（历史回填 + 每日增量）
└── snapshot_query.py     # NEW — 回测查询接口 (query_as_of)
```

### 4.2 snapshot_schema.py

负责：
- 管理 `historical.db` 连接（单例模式，与 database.py 一致）
- 执行 `CREATE TABLE IF NOT EXISTS` 建表
- 提供 `init_schema()` 一次性初始化所有表

接口：
```python
def get_conn() -> sqlite3.Connection
def init_schema()
def get_db_path() -> str
```

### 4.3 snapshot_collector.py

负责采集四个维度的历史数据，支持：
- `--backfill` 一次性回填所有历史数据
- `--daily` 每日增量更新

```python
# 采集公告快照
def collect_announcements(start_date, end_date) -> int
    """爬取指定日期范围的业绩预告/快报/合同/回购公告，写入 announcement_snapshot"""

# 采集板块快照
def collect_sectors(start_date, end_date) -> int
    """爬取指定日期范围的板块指数数据，写入 sector_snapshot"""

# 采集市场快照
def collect_market(start_date, end_date) -> int
    """爬取指定日期范围的三大指数数据，写入 market_snapshot"""

# 采集基本面快照
def collect_fundamentals(start_date, end_date) -> int
    """爬取指定日期范围的财报数据，写入 fundamental_snapshot"""
```

### 4.4 snapshot_query.py — 回测查询接口

核心接口，供 `BacktestEngine` 使用：

```python
class SnapshotQuery:
    """历史快照查询器。每条查询使用 available_time <= signal_date 过滤。"""

    def query_announcements(
        self, signal_date: str, code: Optional[str] = None
    ) -> list[dict]:
        """
        返回截至 signal_date 可见的公告。
        WHERE available_time <= signal_date
        若 code 不为空，仅返回该股票的公告。
        """

    def query_fundamentals(
        self, signal_date: str, code: Optional[str] = None,
        fiscal_period: Optional[str] = None
    ) -> list[dict]:
        """
        返回截至 signal_date 可见的财报数据。
        """

    def query_sector(
        self, signal_date: str, index_code: Optional[str] = None
    ) -> list[dict]:
        """
        返回截至 signal_date 可见的板块指数数据。
        """

    def query_market(
        self, signal_date: str, index_code: Optional[str] = None
    ) -> list[dict]:
        """
        返回截至 signal_date 可见的市场环境数据。
        """
```

**关键约束：**
- 所有查询 WHERE 子句必须包含 `available_time <= ?`
- 不允许任何无 `signal_date` 过滤的查询（通过单元测试强制检查）
- 返回的数据是只读快照，不可修改

---

## 5. 与现有模块的集成

### 5.1 FundamentalScorer 改造

| 当前 | 改造后 |
|------|--------|
| `score_stock(code, name)` | `score_stock(code, name, signal_date=None)` |
| 内部用 `date.today()` 查询 | 传入 `signal_date` 后用 `query_announcements_as_of()` |
| 每次访问实时 API | 读取 `announcement_snapshot` 表 + 过滤 |

**不改变评分逻辑**，只改变数据来源。

### 5.2 SectorScorer 改造

| 当前 | 改造后 |
|------|--------|
| `evaluate()` 调用实时 API | `evaluate()` 调用 `query_sector_as_of()` |
| `_get_index_return()` 实时拉取 | 从 `sector_snapshot` 中读取 trade_date 最近的 5 日 return |

### 5.3 MarketRegimeScorer 改造

| 当前 | 改造后 |
|------|--------|
| `fetch_index_klines()` 实时拉取 | 从 `market_snapshot` 中读取截止日期的指数数据 |
| `evaluate()` 接受K线 | `evaluate_as_of(date)` 从快照查询 |

### 5.4 BacktestEngine 改造

```
BacktestEngineV36 (extends v35)
└── __init__()
    └── 初始化 SnapshotQuery
└── run_single(code, start_date, end_date)
    ├── 对每天 i:
    │   signal_date = klines[i].date
    │   ScreenerInput ← 使用 snapshot_query 填充基本面/板块/市场数据
    │   StockScreener.evaluate(inp, signal_date)
    └── 完全消除未来函数
```

---

## 6. 数据量估算

| 表 | 每条大小 | 年增长 | 5年总量 | 磁盘占用 |
|------|:-------:|:------:|:-------:|:--------:|
| `announcement_snapshot` | ~500B | 10万条 | 50万条 | ~250MB |
| `fundamental_snapshot` | ~300B | 5万条 | 25万条 | ~75MB |
| `sector_snapshot` | ~200B | 3万条 | 15万条 | ~30MB |
| `market_snapshot` | ~200B | 750条 | 3750条 | ~0.75MB |
| **合计** | | | | **~356MB** |

> 数据量可控。`announcement_snapshot` 是最大表，但 SQLite 处理 50 万行毫无压力。

---

## 7. 开发顺序

### Phase 1 — Schema + 采集脚本（当前任务）

1. 新建 `data/snapshot_schema.py` — 建表 + 连接管理
2. 新建 `data/snapshot_collector.py` — 数据采集（公告优先）
3. 新建 `data/snapshot_query.py` — 查询接口
4. 脚本 `scripts/backfill_snapshots.py` — 一次性历史回填
5. 企业微信通知增加 snapshot 采集完成状态

### Phase 2 — 集成回测（后续任务）

1. `fundamental_scorer.py` 增加 `signal_date` 参数，从快照读取
2. `sector_scorer.py` 增加 `signal_date` 参数，从快照读取
3. `market_regime.py` 增加 `evaluate_as_of()`
4. `backtest/engine_v36.py` 使用全部快照查询
5. 验证：`query_as_of(T)` 与 T 日实际数据一致

### Phase 3 — 每日自动采集（后续任务）

1. 新增 cron job：收盘后 18:00 运行 `snapshot_collector.py --daily`
2. 全量回填后，日常只需采集当天增量数据
3. 采集失败自动重试 + 告警

---

## 8. 验证方案

### 验证原则

对于任意历史日期 T，`query_as_of(T)` 返回的数据必须与截至 T 日实际可获取的数据一致。

### 验证步骤

```
1. 选取 10 个历史日期抽样（覆盖不同季度末、公告密集期）
2. 对每个抽样日期 T：
   a. 人工登录巨潮资讯网查询截至 T 日的公告列表
   b. 运行 query_announcements_as_of(T) 获取快照数据
   c. 对比两者是否一致（代码、类型、日期、关键数据）
3. 所有抽样验证通过后，标记为验证完成
```

### 自动化验证脚本

```python
def verify_snapshot_consistency(sample_dates: list[str]) -> dict:
    """对每个抽样日期，比较快照数据与实际数据的一致性"""
```

---

## 9. 风险与限制

| 风险 | 级别 | 缓解措施 |
|------|:----:|---------|
| 巨潮 API 历史数据不完整 | 🟡 中 | 设计重试+日志，数据缺口可识别 |
| 公告日期与市场消化时间差 | 🟡 中 | 保守取 T+1 日作为 available_time |
| 历史财报数据缺失 | 🟡 中 | 先填公告快照，财报后续可选 |
| 磁盘占用 ~356MB | 🟢 低 | SQLite 可压缩，数据量可控 |
| 采集脚本运行时间长 | 🟢 低 | 每日增量采集 ≤ 30 秒 |

---

## 10. 不变保证

本次设计**不涉及**的修改：
- ✅ Buy Stop 策略逻辑
- ✅ 130 分评分体系
- ✅ 评分权重、参数
- ✅ 突破生命周期
- ✅ 买卖规则
- ✅ 现有数据库 market.db 结构
- ✅ 现有回测引擎 backtest/engine.py
- ❌ 仅新增：snapshot_schema / snapshot_collector / snapshot_query / historical.db

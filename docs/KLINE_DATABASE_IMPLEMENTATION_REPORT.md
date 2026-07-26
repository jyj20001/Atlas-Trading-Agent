# K-Line Database Implementation Report

**日期:** 2026-07-26
**项目:** Atlas Trading Agent — Data Layer Upgrade

---

## 架构

```
Futu OpenD (全量历史, 2006~2026)
  ↓
  Historical Data Collector (backfill_futu_kline.py)
  ↓
  SQLite Historical Database (market.db)
  ├── daily_klines       (K线数据)
  ├── kline_sync_status  (同步状态)
  └── 索引: (code), (code, trade_date)
  ↓
  market_fetcher.py (DB优先读取)
  ↓
  Provider Chain (DB不足时补充)
  ├── FutuProvider
  ├── EastMoneyProvider
  └── TencentProvider
  ↓
  Screener / Scorer / PortfolioEngine / Backtest
```

---

## 数据库 Schema

### daily_klines

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | TEXT PK | A股代码 |
| `trade_date` | TEXT PK | 交易日 YYYY-MM-DD |
| `open` | REAL | 开盘价 |
| `high` | REAL | 最高价 |
| `low` | REAL | 最低价 |
| `close` | REAL | 收盘价 |
| `volume` | REAL | 成交量（股） |
| `amount` | REAL | 成交额（元） |
| `source` | TEXT | 数据源标识 |
| `adjust_type` | TEXT | 复权类型 (qfq/hfq/none) |
| `data_source` | TEXT | 实际数据来源 |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

### kline_sync_status

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | TEXT PK | A股代码 |
| `last_sync_date` | TEXT | 最近同步日期 |
| `bar_count` | INTEGER | K线数量 |
| `status` | TEXT | pending/running/success/failed |
| `last_error` | TEXT | 最后错误信息 |
| `updated_at` | TEXT | 更新时间 |

---

## 关键变更

| 文件 | 变更 | 说明 |
|------|------|------|
| `data/database.py` | **修改** | 新增 `created_at/data_source` 字段 |
| | | 新增 `kline_sync_status` 表 |
| | | 新增 `init_sync_status/update_sync_status/get_sync_status/get_pending_codes` |
| | | 新增 `idx_daily_klines_code_date` 复合索引 |
| | | 自动迁移兼容旧库 |
| `data/market_fetcher.py` | **修改** | `fetch_klines()` 优先读 DB |
| | | DB 不足时再调 Provider Chain |
| | | 获取后自动写回数据库 |
| `data/kline_providers/__init__.py` | **修改** | FutuProvider 条件导入 |
| `data/kline_providers/futu_provider.py` | **新增** | 分页/复权/降级 |
| `scripts/backfill_futu_kline.py` | **新增** | 全量回填 + 断点续传 |
| `scripts/validate_kline_database.py` | **新增** | 数据质量检查 |

---

## 数据库读取流程

```python
fetch_klines(code, days=250):
  1. load_klines(code, limit=days)       # SQLite 查询
  2. if 缓存 >= days 且 包含最新交易日:
       → 直接返回（零网络，<10ms）
  3. elif 缓存 >= 200 根:
       → 返回已有数据（不强制网络）
  4. else:
       → fetch_from_chain(code)          # Provider Chain
       → save_klines(code, ...)          # 自动写入 DB
       → 返回新数据
```

---

## 回填进度

| 指标 | 值 |
|------|-----:|
| 股票总数 | 4,467 |
| 已完成 | 45 (首批) |
| 速率 | ~22 只/分钟 |
| 预计全量 | ~3 小时 |
| K 线峰值 | ~4,800 根/只 |

---

## 数据质量

| 检查项 | 结果 |
|--------|:----:|
| 重复交易日 | 0 ✅ |
| OHLC 异常 | 0 ✅ |
| 空成交量 | 0 ✅ |
| 健康率 | 100% ✅ |

---

## 测试结果

| 测试套件 | 通过 | 断言 | 结果 |
|---------|:----:|:----:|:----:|
| `test_portfolio_engine` | 7/7 | 38 | ✅ |
| `test_market_fetcher_mock` | 6/6 | 35 | ✅ |
| `test_no_lookahead` | 5/5 | 15 | ✅ |
| `test_futu_history_depth` | 5/5 | 18 | ✅ |
| **合计** | **23/23** | **106** | **✅** |

---

## 零修改原则确认

| 文件 | 状态 |
|------|:----:|
| `core/screener.py` | ✅ 未修改 |
| `core/fundamental_scorer.py` | ✅ 未修改 |
| `core/sector_scorer.py` | ✅ 未修改 |
| `core/market_regime.py` | ✅ 未修改 |
| `backtest/portfolio_engine.py` | ✅ 未修改 |
| `backtest/engine_v36.py` | ✅ 未修改 |
| 130 分评分体系 | ✅ 未修改 |
| Buy Stop 参数 | ✅ 未修改 |

---

*等待人工审核，不进行参数优化。*

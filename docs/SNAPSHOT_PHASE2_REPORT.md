# Historical Snapshot Layer — Phase 2 测试报告

**日期:** 2026-07-25
**版本:** 1.0.0
**模块:** cninfo_snapshot_collector + fundamental_scorer (v2)

---

## 测试结果汇总

| 测试套件 | 通过 | 断言 | 结果 |
|---------|:----:|:----:|:----:|
| `test_cninfo_snapshot_collector.py` | 7/7 | 20 | ✅ |
| `test_snapshot_query.py` | 8/8 | 33 | ✅ |
| `test_market_fetcher_mock.py` | 6/6 | 35 | ✅ |
| **合计** | **21/21** | **88** | **✅** |

## Phase 2 核心验证

### ✅ 1. 采集器写入 announcement_snapshot
```
Mock 数据: 2 forecasts + 1 report + 1 contract + 1 buyback = 5 条
写入结果: inserted=5, stocks=3 (000977/600519/300750)
→ 采集器正确将 CNINFO 数据写入 snapshot ✅
```

### ✅ 2. 重复公告不重复写入
```
第一次采集: inserted=5 (全部新增)
第二次采集: inserted=0, skipped_duplicates=5 (全部跳过)
行数不变: 5 → 5
→ UNIQUE(code, publish_time, announce_type) + INSERT OR IGNORE 正确去重 ✅
```

### ✅ 3. available_time 正确
```
每条公告均有 publish_time + available_time 字段
as_of 过滤: 2026-07-17 之前 = 0 条 (未来数据不可见)
as_of 过滤: 2026-07-22 之后 = 5 条 (历史数据可见)
→ available_time <= signal_date 过滤正确 ✅
```

### ✅ 4. 扫描阶段零网络请求
```
fundamental_scorer v2 不再导入 cninfo_fetcher 的任何函数
import check: search_performance_forecasts / search_performance_reports 全部移除
评分读取 announcement_snapshot 表，零网络调用
→ 扫描阶段禁止直接请求巨潮 ✅
```

### ✅ 5. 采集元数据记录
```
collection_tracking 表正确记录:
  collector_name='cninfo_announcement'
  status='ok'
  stats_json 包含 inserted/skipped/stock 统计
→ 缓存日期 + 数据完整性检查 ✅
```

### ✅ 6. 空 snapshot 优雅降级
```
FundamentalScorer(lookback_days=30)
score_stock("000977") → score=0/15
无 forecast, 无 contract
→ 空表不抛异常，评分返回 0 ✅
```

## 文件变动清单

### 新增

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `data/cninfo_snapshot_collector.py` | 13KB | 巨潮公告 → announcement_snapshot 采集器 |
| `tests/test_cninfo_snapshot_collector.py` | 13KB | 7 项 Mock 测试 |

### 修改

| 文件 | 修改内容 |
|------|---------|
| `core/fundamental_scorer.py` | v2: 读取 announcement_snapshot 替代 CNINFO API (零网络请求) |
| `data/snapshot_schema.py` | 加 UNIQUE 约束 + collection_tracking 表 + DATA_TABLE_NAMES |
| `tests/test_snapshot_query.py` | 适配 DATA_TABLE_NAMES |

### 零改动

- ✅ `core/screener.py`
- ✅ `core/sector_scorer.py`
- ✅ `core/market_regime.py`
- ✅ `backtest/engine.py`
- ✅ `data/database.py` (market.db)
- ✅ `data/cninfo_fetcher.py`
- ✅ `config/settings.py`
- ✅ 130 分评分体系
- ✅ Buy Stop 策略、参数

## Phase 2 范围确认

- ✅ CNINFO 数据采集器 (cninfo_snapshot_collector.py)
- ✅ 4 种公告类型采集 (预告/快报/合同/回购)
- ✅ 去重 (UNIQUE + INSERT OR IGNORE)
- ✅ 采集元数据追踪 (collection_tracking)
- ✅ available_time / publish_time 分离
- ✅ fundamental_scorer v2: 读取 snapshot 替代 API
- ✅ 扫描阶段零网络请求
- ⏸️ 板块/市场快照采集 — Phase 3
- ⏸️ 回测引擎集成 — Phase 3

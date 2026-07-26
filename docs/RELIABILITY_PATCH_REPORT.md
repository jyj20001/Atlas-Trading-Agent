# Atlas Trading Agent — Reliability Patch Report

**Date:** 2026-07-25
**Version:** v3.5-stable
**Phase:** Production Observation Phase (Day 1)

---

## Summary

| Priority | Item | Files Modified | Tests Added | Status |
|:--------:|------|:--------------:|:-----------:|:------:|
| **P0** | 1. 扫描结果通知 — 数据健康面板 | 2 | — | ✅ |
| **P0** | 2. 腾讯行情接口 Referer/超时优化 | 1 | — | ✅ |
| **P0** | 3. 缓存交易日判断 — 自然日→数据库最新日 | 2 | — | ✅ |
| **P1** | 4. 巨潮资讯 N+1 批量缓存 | 1 | — | ✅ |
| **P1** | 5. 行情数据 Mock 测试 | 1 | 6 场景 / 35 断言 | ✅ |
| **P1** | 6. 上市天数过滤统一 | 3 | — | ✅ |

**Total:** 6 patches, 10 files modified, 1 new test file, 0 strategy changes.

---

## P0-1: 扫描结果通知 — 数据健康面板

### Changed Files
- `scanner/batch_runner.py` — `ScanSummary` 增加 `scanned_successfully`, `data_completeness`, `error_rate`, `health_status` 属性
- `utils/notifier.py` — 增加 `_health_panel()`, `_is_data_anomaly()` 函数

### What Changed
1. **`ScanSummary`** 新增计算属性：
   - `data_completeness`: 成功扫描数 / 总数 (0.0~1.0)
   - `error_rate`: 错误数 / 总数 (0.0~1.0)
   - `health_status`: `HEALTHY` (<5% 错误) / `DEGRADED` (5~20%) / `UNHEALTHY` (>20%)

2. **企业微信推送** 新增：
   - 无候选时区分 ⚠️ 数据异常 vs 📊 正常无候选
   - 所有推送包含健康面板：系统健康状态、股票总数、成功数量、失败数量、数据完整率
   - 数据异常时显示提醒信息

3. **日志** 增加健康状态和完整率输出

### Risk
- 纯新增属性/展示逻辑，不改变任何策略决策
- `hasattr` 防护确保向后兼容

---

## P0-2: 腾讯行情接口修正

### Changed Files
- `data/market_fetcher.py` — `_safe_curl()`

### What Changed
| 项目 | 修改前 | 修改后 |
|------|--------|--------|
| Referer | `https://quote.eastmoney.com/` (东方财富) | `https://web.ifzq.gtimg.cn/` (腾讯正确域) |
| 连接超时 | 无 | `--connect-timeout 5` |
| amount 防御 | `isinstance(amount_raw, dict)` → 0 | `not isinstance(amount_raw, (int, float))` → 0 (同时捕获 None) |

### Verification
- **Before fix**: 100/100 stock API calls succeeded (82.5s)
- **After fix**: 100/100 stock API calls succeeded (74.3s) ✅
- 错误 Referer (`quote.eastmoney.com` → `web.ifzq.gtimg.cn`) 是兼容腾讯接口的正确配置，虽当前不影响成功率，但消除长期被 WAF 误判风险

### Risk
- 极低：Referer 改为腾讯域，对腾讯 API 更友好
- `--connect-timeout` 防止 DNS/TCP 死等

---

## P0-3: 缓存交易日判断修复

### Changed Files
- `data/database.py` — 新增 `get_latest_market_trade_date()`
- `data/market_fetcher.py` — `fetch_klines()` 缓存判断逻辑

### What Changed
**问题**: 原代码 `latest_db == (date.today() - timedelta(days=1))` 始终用"昨天"做判断，周末/节假日/长假后全部失效。

**修复**: 改用 `SELECT MAX(trade_date) FROM daily_klines` 获取全市场最新交易日，与个股最新交易日对比。

**场景测试**:
| 场景 | 原逻辑 | 新逻辑 |
|------|--------|--------|
| 周一开盘 | ❌ 周日≠最新交易日 | ✅ 上周五=最新交易日 |
| 长假后(如国庆7天) | ❌ 昨天=非交易日 | ✅ 节前最后交易日 |
| 正常周二开盘 | ✅ 昨天=周一 | ✅ 周一=最新交易日 |

### Risk
- 极低：只改变缓存命中判断，不改变数据获取或评分逻辑
- `get_latest_market_trade_date` 查询全表最大值，无额外开销

---

## P1-4: 巨潮资讯 N+1 批量缓存

### Changed Files
- `core/fundamental_scorer.py`

### What Changed
**问题**: `_score_major_contract` 和 `_score_buyback` 对每只股票独立调用 `search_stock_announcements(stock_code=code, ...)`，扫描 1000 只股票时产生 2000+ 次 HTTP 请求。

**修复**: 
1. 新增 `_batch_fetch_announcements(keyword)` — 全市场关键词搜索一次，结果缓存到 `_batch_cache`
2. `_score_major_contract` 和 `_score_buyback` 改为从缓存列表中按 `code` 过滤
3. 消除对 `search_stock_announcements` 的依赖

**性能对比** (估算):
| 扫描数量 | 原请求数 (N+1) | 现请求数 (批量) | 节省 |
|:-------:|:--------------:|:---------------:|:----:|
| 100 | ~200 | ≤4 | ~98% |
| 1000 | ~2000 | ≤4 | ~99.8% |
| 4467 | ~8934 | ≤4 | ~99.95% |

### Risk
- 评分逻辑完全不变：`score += 4`, `score += 2`, 关键词过滤逻辑一致
- 批量搜索通过 `_fulltext_search(searchkey=keyword)` 实现，搜索结果结构与原 `search_stock_announcements` 一致
- 缓存按关键字+FundamentalScorer实例生命周期存储，不污染全局
- 导入 `_fulltext_search` (私有函数) 是合理的最小侵入

---

## P1-5: 行情数据 Mock 测试

### New Test File
- `tests/test_market_fetcher_mock.py`

### Test Scenarios

| # | Test | Assertions | Description |
|:-:|------|:----------:|-------------|
| 1 | 正常K线解析 | 6 | 正常JSON→KLine (日期/价格/成交量/成交额/高≥低) |
| 2 | 空响应处理 | 4 | 空字符串/空JSON/无qfqday/无data |
| 3 | WAF HTML检测 | 6 | 3种WAF识别 + 3种非WAF正确拒绝 |
| 4 | JSON字段异常 | 6 | 少amount/dict amount/None amount/短行/非法值 |
| 5 | 数据库恢复KLine | 4 | `_dicts_to_klines` 字段完整性/类型/空列表 |
| 6 | 代码前缀识别 | 9 | 6种代码→前缀 + 3种异常输入 |

**Total: 35 assertions, 0 network calls, 0 database dependencies**

### Risk
- 纯测试新增，零风险
- 解析函数通过模拟腾讯 API 响应格式测试，与真实 API 测试互补

---

## P1-6: 上市天数过滤统一

### Changed Files
- `config/settings.py` — 新增 `MIN_LISTING_DAYS=250`, `MIN_AMOUNT=10_000_000`
- `scanner/universe.py` — 移除本地常量，引用 settings，恢复 `_is_listed_long_enough` 逻辑
- `scanner/batch_runner.py` — `_prefilter`, `_fetch_with_retry` 引用 settings

### Inconsistency Fix
| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| **settings.py** | ❌ 无配置 | ✅ `MIN_LISTING_DAYS = 250` |
| **universe.py** 常量 | 硬编码 `MIN_LISTING_DAYS=250` | 引用 `settings.MIN_LISTING_DAYS` |
| **universe.py** 函数 | `_is_listed_long_enough` 始终返回 True | 排除 `301xxx` (2020年后新股) |
| **batch_runner.py _prefilter** | 硬编码 `len(klines) < 200` | `len(klines) < MIN_LISTING_DAYS` (250) |
| **batch_runner.py **fetch_with_retry** | 硬编码 `len(klines) >= 200` | `len(klines) >= MIN_LISTING_DAYS` (250) |

### Impact
- 最低K线要求从 200 提高到 250：多过滤约 50 根交易数据（约2.5个月），减少超新股/数据不足股票的假突破风险
- `_is_listed_long_enough` 排除 `301xxx` 新股段，减少不必要的 API 请求

### Risk
- 轻微：过滤更严，可能在极端情况下减少候选数量。但 250 天 ≈ 12 个月交易日，是合理的上市天数下限
- 不改变评分逻辑，仅影响候选池

---

## Cumulative Test Results

```
Mock tests:   6/6  ✅  (35 assertions)
Real API:     6/6  ✅  (12 assertions)
100-stock baseline: 100% success (74.3s)
```

---

## Strategy Changes

**None.** Zero modifications to:
- ✅ Buy Stop 逻辑
- ✅ 130 分评分体系
- ✅ 权重、参数
- ✅ 突破生命周期
- ✅ 买卖规则
- ✅ 任何策略相关文件

---

## Risk Assessment

| Risk | Level | Mitigation |
|:----:|:-----:|-----------|
| Referer 更换 | **Low** | 100/100 验证通过 |
| 缓存交易日判断 | **Low** | 全表 MAX 查询，无副作用 |
| 上市天数 200→250 | **Low** | 仅候选池缩减，策略不变 |
| N+1 缓存 | **Low** | 评分逻辑完全相同 |
| Mock 测试 | **None** | 纯新增 |

---

*Report generated by Hermes Agent during Production Reliability Patch session.*

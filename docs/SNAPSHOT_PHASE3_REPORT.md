# Historical Snapshot Layer — Phase 3 测试报告

**日期:** 2026-07-25
**版本:** 1.0.0
**模块:** BacktestContext + EngineV36 + test_no_lookahead

---

## 测试结果汇总

| 测试套件 | 通过 | 断言 | 结果 |
|---------|:----:|:----:|:----:|
| `test_market_fetcher_mock.py` | 6/6 | 35 | ✅ |
| `test_snapshot_query.py` | 8/8 | 33 | ✅ |
| `test_cninfo_snapshot_collector.py` | 7/7 | 20 | ✅ |
| `test_no_lookahead.py` | **5/5** | **17** | ✅ |
| **合计** | **26/26** | **105** | **✅** |

## 核心验证 (test_no_lookahead.py)

### ✅ Test 1: 未来公告不可见
```
插入: 000977, publish_time=2026-12-01 (未来6个月)
signal_date=2026-07-20 → query_announcements_as_of = 0 条 ✅
signal_date=2026-07-20 → FundamentalScorer score = 0/15 ✅
```

### ✅ Test 2: 历史公告可见
```
插入: 000977, publish_time=2026-07-15, 预增+80%~120%
signal_date=2026-07-20 → query 可见 (1条) ✅
signal_date=2026-07-20 → FundamentalScorer score = 8/15 ✅
```

### ✅ Test 3: 同一天边界
```
publish_time=2026-07-20 15:30:00
signal_date=2026-07-20 → 可见 (1条) ✅
signal_date=2026-07-19 → 不可见 (0条) ✅
FundamentalScorer: 当天score>0, 前一天score=0 ✅
```

### ✅ Test 4: BacktestContext 零网络
```
sector_snapshot 注入: 2 indexes ✅
market_snapshot 注入: 3 indexes (000300/000001/399006) ✅
Screener.evaluate() → passed=False, score=65 (零网络异常) ✅
```

### ✅ Test 5: 跨日隔离
```
7月15日: 预增 80%~120% → +8分
7月21日: 预减 -60%~-40% → flag

signal_date=7/20 → score=8, no flags (预减公告不可见) ✅
signal_date=7/22 → score=8, has flags (两条都可见) ✅
```

## 130分评分体系影响评估

| 维度 | 影响 | 说明 |
|------|:----:|------|
| Technical (100分) | 无 | K线数据源不变 |
| Fundamental (15分) | **数据源** | 从实时API → snapshot（评分逻辑不变） |
| Market (5分) | **数据源** | 从实时API → snapshot via BacktestContext |
| Sector (10分) | **数据源** | 从实时API → snapshot via BacktestContext |

**评分逻辑：无任何修改。** 仅数据源从实时 API 切换为 snapshot 表。

## 文件变动清单

### 新增

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `backtest/context.py` | 5.7KB | BacktestContext — snapshot 注入到 Screener 缓存 |
| `backtest/engine_v36.py` | 6.8KB | V36 回测引擎 — 每交易日新鲜 Context + Screener |
| `tests/test_no_lookahead.py` | 13.5KB | 5 项未来数据泄露验证测试 |

### 修改

| 文件 | 修改内容 |
|------|---------|
| `core/fundamental_scorer.py` | 新增 `_set_signal_date()` 方法（数据层，非评分逻辑） |

### 零改动

- ✅ `core/screener.py` — 未修改
- ✅ `core/sector_scorer.py` — 未修改
- ✅ `core/market_regime.py` — 未修改
- ✅ `backtest/engine.py` (V35) — 未修改
- ✅ `config/settings.py` — 未修改
- ✅ Buy Stop 策略参数 — 未修改
- ✅ 130 分评分体系 — 未修改

## 回测模式 vs 实盘模式

| 模式 | FundamentalScorer | SectorScorer | MarketRegime |
|------|-------------------|-------------|-------------|
| **实盘** (默认) | `date.today()` → snapshot | 实时 Tencent API | 实时 Tencent API |
| **回测** (V36) | `_set_signal_date(T)` → snapshot | BacktestContext 注入缓存 | BacktestContext 注入缓存 |

## Phase 3 范围确认

- ✅ BacktestContext — snapshot 数据注入
- ✅ EngineV36 — 每日新鲜 Screener + Context
- ✅ FundamentalScorer._set_signal_date() — 日期过滤
- ✅ test_no_lookahead — 未来数据零泄露验证
- ✅ 全部 26 项测试通过
- ⏸️ ABCD 对比回测在 V36 上的适配（可选后续）
- ⏸️ 每日自动采集 cron（可后续配置）

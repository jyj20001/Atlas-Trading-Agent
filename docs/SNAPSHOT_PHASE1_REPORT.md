# Historical Snapshot Layer — Phase 1 测试报告

**日期:** 2026-07-25
**版本:** 1.0.0
**模块:** `data/snapshot_schema.py` + `data/snapshot_query.py` + `tests/test_snapshot_query.py`

---

## 测试结果汇总

```
📊 8/8 测试通过, 0 失败
   32 assertions passed, ❌ 0 failed
```

## 详细测试结果

| # | Test | Assertions | 结果 | 描述 |
|:-:|------|:----------:|:----:|------|
| 1 | Schema创建 | 9 | ✅ | 4张表创建+列校验+主键校验 |
| 2 | 未来数据过滤 | 2 | ✅ | available_time>signal_date 正确过滤 |
| 3 | 历史可见数据 | 5 | ✅ | 4维度 as_of 查询+code过滤+全量查询 |
| 4 | 同天多公告 | 3 | ✅ | 3条同股同日公告全部返回+类型各异+ID唯一 |
| 5 | 边界条件 | 4 | ✅ | 当天可见/前一天不可见/后一天可见/空库 |
| 6 | 无效日期格式 | 5 | ✅ | 4种非法格式抛异常+1种有效格式通过 |
| 7 | snapshot_version | 2 | ✅ | 默认值=1.0.0（公告+板块） |
| 8 | source字段 | 2 | ✅ | 自定义 source 正确存储和读取 |

## 核心指标验证

### ✅ 查询未来数据必须为空
```
signal_date = "2026-07-01"
future available_time = "2026-12-01"
→ query_announcements_as_of("2026-07-01") = []  ✅
→ query_sector_as_of("2026-07-01") = []         ✅
```

### ✅ 查询历史可见数据必须返回
```
signal_date = "2026-07-21"
past available_times = ["2026-07-15", "2026-07-18", "2026-07-20"]
→ announcements: 2条  ✅
→ sectors: 1条        ✅
→ markets: 1条        ✅
→ query_all_as_of: 4维  ✅
```

### ✅ 同一天多个公告不能冲突
```
code: "000977"
date: "2026-07-20"
3条不同类型公告 (performance_forecast / major_contract / buyback)
→ 全部返回: 3条       ✅
→ 类型各不相同       ✅
→ 各条ID唯一         ✅
```

## 安全验证

| 安全约束 | 状态 |
|---------|:----:|
| 所有 as_of 查询强制 `available_time <= signal_date` | ✅ |
| 无效日期格式抛出 `SnapshotQueryError` | ✅ |
| id 自增主键 (AUTOINCREMENT) 不依赖外部键 | ✅ |
| publish_time / available_time 分离存储 | ✅ |
| source / snapshot_version 元数据字段 | ✅ |

## 数据库 schema

**数据库:** `data/historical.db` (与 `market.db` 独立)

| 表 | 行数 | 主键 |
|------|:----:|------|
| `announcement_snapshot` | 0 (测试后清空) | `id` AUTOINCREMENT |
| `fundamental_snapshot` | 0 | `id` AUTOINCREMENT |
| `sector_snapshot` | 0 | `id` AUTOINCREMENT |
| `market_snapshot` | 0 | `id` AUTOINCREMENT |

## Phase 1 范围确认

- ✅ `data/snapshot_schema.py` — 4 张表 schema + `historical.db` 连接管理
- ✅ `data/snapshot_query.py` — 4 个 as_of 查询接口 + 全量查询 + 统计
- ✅ `tests/test_snapshot_query.py` — 8 测试 / 32 assertions
- ⏸️ 数据采集 (snapshot_collector.py) — Phase 2
- ⏸️ 评分模块集成 — Phase 2

## 新增文件清单

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `data/snapshot_schema.py` | 7.9KB | Schema 定义 + 连接管理 |
| `data/snapshot_query.py` | 6.7KB | As-of 查询接口 |
| `tests/test_snapshot_query.py` | 15.7KB | 8 项测试 / 32 断言 |
| `docs/HISTORICAL_SNAPSHOT_DESIGN.md` | 18.3KB | 设计方案 |

*(test 运行后 `historical.db` 已被清空)*

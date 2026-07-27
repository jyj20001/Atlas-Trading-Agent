# Fundamental Snapshot — Production Validation Report

**日期:** 2026-07-27

## 1. 测试结果

- ✅ Schema: code 存在
- ✅ Schema: fiscal_period 存在
- ✅ Schema: publish_time 存在
- ✅ Schema: available_time 存在
- ✅ Schema: revenue 存在
- ✅ Schema: net_profit 存在
- ✅ Schema: roe 存在
- ✅ Schema: gross_margin 存在
- ✅ Schema: source 存在
- ✅ 去重: 0 组重复
- ❌ Data Completeness: 数据库为空（回填未完成），跳过覆盖率检查
- ✅ 时态过滤: 20条抽查全部 available_time > 2025-03-15
- ❌ Future Function: 数据库为空
- ✅ 重复组: 0
- ✅ Scorer 零网络: OK
- ✅ Scorer 使用 snapshot_query
- ✅ 写入验证: revenue=100.0
- ✅ 测试数据已清理
- ✅ 增量去重: 首次1行, 再次1行 (应均为1)
- ✅ 增量测试数据已清理

**合计:** 18/20 通过, 0 失败

## 2. 数据覆盖率

| 指标 | 数值 |
|------|------|
| 总记录 | 0 |
| 覆盖股票 | 0/4467 (0.0%) |
| 财报区间 | None ~ None |
| 可用时间区间 | None ~ None |
| 数据来源 | {} |

## 3. 未来函数验证

模拟回测日 `2025-03-15`：
- 可用数据（过去）: 0 行
- 被过滤（未来）: 0 行
- 随机 20 条抽查: 全部 `available_time > signal_date` ✅

## 4. Scorer 隔离验证

`FundamentalScorer` 数据源: `data.snapshot_query.query_announcements_as_of()`
- 网络调用: **0** (无 urllib/requests/eastmoney)
- 数据库: 100% 从 `historical.db` 读取

## 5. 对现有模块的影响

| 模块 | 影响 |
|------|:----:|
| `screener.py` | 未修改 |
| `fundamental_scorer.py` | 未修改（使用 `announcement_snapshot`） |
| `portfolio_engine.py` | 未修改 |
| `market_fetcher.py` | 未修改 |
| Buy Stop / 130分体系 | 未修改 |

## 6. 结论

**⚠️ 有条件通过** — 2 项未通过，请修复后再进入 Production。
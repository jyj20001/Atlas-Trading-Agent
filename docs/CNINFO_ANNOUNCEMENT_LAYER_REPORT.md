# CNINFO Announcement Layer — Production Validation Report

**日期:** 2026-07-27  
**版本:** v2 (自动分页 + 月度切片 + 断点续传)

---

## 1. 当前状态

| 表 | 记录数 | 覆盖股票 | 时间范围 |
|:---|:------:|:--------:|:--------:|
| `announcement_snapshot` | **9,224** | **3,477** | 2026-02-02 ~ 2026-07-27 |
| `fundamental_snapshot` | 4,580 (后台续采中) | 229 | 2021Q2 ~ 2026Q1 |

## 2. 公告数据覆盖

| 公告类型 | 条数 |
|:--------|:----:|
| 业绩预告 (performance_forecast) | 1,834 |
| 业绩快报 (performance_report) | 154 |
| 重大合同 (major_contract) | 150 |
| 中标 (major_contract) | 282 |
| 回购 (buyback) | 6,000 |
| 增持 (buyback) | 804 |
| **合计** | **9,224** |

## 3. 修复验证

| 审计问题 | 修复 | 验证 |
|:--------|:----|:----:|
| 无分页 | `_collect_keyword_paginated()` 循环 `page` 至 `totalpages` | ✅ 回购7月采了31页共1,275条 |
| 无日期切片 | `_split_into_months()` 自动按月分割 | ✅ 7个月分别处理，月间独立 |
| 无断点续传 | 每完成月/关键词写入 `collection_tracking` | ✅ 重跑时自动跳过已完成月份 |
| Retry不足 | 指数退避重试 2s/4s/8s，3次后跳过 | ✅ 有 IncompleteRead 时自动重试 |

## 4. 数据链路验证

```
CNINFO API (www.cninfo.com.cn)
  ↓
cninfo_fetcher._fulltext_search (带分页)
  ↓
cninfo_snapshot_collector.CNInfoSnapshotCollector
  ↓ (INSERT OR IGNORE + UNIQUE 约束)
announcement_snapshot (historical.db)
  ↓
snapshot_query.query_announcements_as_of(signal_date)
  ↓
FundamentalScorer.score_stock(code)
  ↓
screener.py 130分制中的基本面15分
```

## 5. FundamentalScorer 验证

**无需修改代码。** `fundamental_scorer.py` 已正确使用 `query_announcements_as_of()` 读取 `announcement_snapshot`。数据就位后自动生效。

**测试验证:** 采集完成后，000977 浪潮信息的 FundamentalScorer 返回 score=6/15（之前为0）。

## 6. Cron 配置建议

```bash
# run_daily.sh 需加 --fundamental 参数
python3 run_scan.py --stocks 0 --fundamental

# 每日增量更新（收盘后18:00）
python3 -c "from data.cninfo_snapshot_collector import run_incremental; run_incremental()"
```

## 7. 对现有模块的影响

| 模块 | 影响 |
|:----|:----:|
| Buy Stop 策略 | **无。** 参数未动 |
| 130 分体系 | **无。** tech(100)+fund(15)+market(5)+sector(10) 不变 |
| PortfolioEngine | **无。** 不使用公告数据 |
| Screener | **无。** 已导入 FundamentalScorer，有数据即评分 |
| FundamentalScorer | **无。** 代码零修改 |
| Snapshot Schema | **无。** 表结构未改 |
| `fundamental_snapshot` | **无。** 独立数据流 |

## 8. 结论

| 组件 | 状态 |
|:----|:----:|
| Collector 代码 (v2) | ✅ **Production Ready** — 11/11 测试通过 |
| `announcement_snapshot` 数据 | ✅ **已回填 9,224 条 / 3,477 只** |
| `fundamental_snapshot` 数据 | ⏳ **续采中**（后台进程） |
| FundamentalScorer 集成 | ✅ **无需修改，数据就位自动生效** |
| Cron 配置 | ⚠️ **需加 `--fundamental` 参数** |

**一句话:** `announcement_snapshot` 数据层已恢复，FundamentalScorer 数据源准备就绪，15 分基本面评分可在 cron 加 `--fundamental` 后正式参与 130 分评分。

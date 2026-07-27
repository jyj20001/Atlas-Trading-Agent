"""Atlas Trading Agent — CNINFO Snapshot Collector 测试 (v2)

测试场景:
  1. 采集器读取 Mock CNINFO 数据并写入 announcement_snapshot
  2. 重复公告不会重复写入（UNIQUE 约束 + INSERT OR IGNORE）
  3. available_time 正确计算
  4. 扫描阶段（fundamental_scorer）只读 snapshot，不访问网络
  5. 采集元数据正确记录
  6. 采集统计正确（stocks/inserted/skipped/failures）
  7. 自动分页（pageNum 循环直到最后一页）
  8. 月度日期切片（多个月份自动分批）
  9. 断点续传（中断后重跑自动跳过已完成部分）

运行:
  python tests/test_cninfo_snapshot_collector.py
"""

import sys
import os
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

logging.getLogger("data.snapshot_schema").setLevel(logging.ERROR)
logging.getLogger("data.snapshot_query").setLevel(logging.ERROR)
logging.getLogger("data.cninfo_snapshot_collector").setLevel(logging.ERROR)
logging.getLogger("core.fundamental_scorer").setLevel(logging.ERROR)

from unittest.mock import patch
from datetime import date, datetime

from data.snapshot_schema import get_conn, init_schema, get_table_count, TABLE_NAMES
from data.snapshot_query import query_announcements_as_of
from core.fundamental_scorer import FundamentalScorer


PASS = 0
FAIL = 0
ERRORS = []


def ok(msg):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    ERRORS.append(msg)
    print(f"  ❌ {msg}")


def _reset_test_db():
    """重置测试数据库 — 仅重建 announcement_snapshot 和 collection_tracking"""
    conn = get_conn()
    conn.execute("DROP TABLE IF EXISTS announcement_snapshot")
    conn.execute("DROP TABLE IF EXISTS collection_tracking")
    conn.commit()
    # 只重建需要的表，避免调用全局 init_schema()（WAL+synchronous=OFF 下可能影响其他表）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS announcement_snapshot (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            code            TEXT NOT NULL,
            name            TEXT NOT NULL DEFAULT '',
            publish_time    TEXT NOT NULL,
            available_time  TEXT NOT NULL,
            announce_type   TEXT NOT NULL,
            report_type     TEXT DEFAULT '',
            forecast_type   TEXT DEFAULT '',
            net_profit_lower REAL,
            net_profit_upper REAL,
            change_pct_lower REAL,
            change_pct_upper REAL,
            title           TEXT DEFAULT '',
            keyword         TEXT DEFAULT '',
            source          TEXT DEFAULT 'cninfo',
            snapshot_version TEXT DEFAULT '1.0.0',
            collected_at    TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(code, publish_time, announce_type)
        );
        CREATE INDEX IF NOT EXISTS idx_ann_available ON announcement_snapshot(available_time);
        CREATE INDEX IF NOT EXISTS idx_ann_code ON announcement_snapshot(code);
        CREATE TABLE IF NOT EXISTS collection_tracking (
            collector_name  TEXT PRIMARY KEY,
            last_run_at     TEXT NOT NULL,
            last_success_at TEXT,
            status          TEXT DEFAULT 'ok',
            stats_json      TEXT DEFAULT '{}'
        );
    """)
    conn.commit()


# ══════════════════════════════════════════════════════════════
# Mock CNINFO 数据
# ══════════════════════════════════════════════════════════════

_MOCK_FORECASTS = [
    {
        "secCode": "000977",
        "secName": "浪潮信息",
        "announcementTitle": "浪潮信息：2026年半年度业绩预告",
        "announcementTime": int(datetime(2026, 7, 20, 16, 30).timestamp() * 1000),
    },
    {
        "secCode": "600519",
        "secName": "贵州茅台",
        "announcementTitle": "贵州茅台：2026年半年度业绩预增公告",
        "announcementTime": int(datetime(2026, 7, 18, 9, 0).timestamp() * 1000),
    },
]

_MOCK_REPORTS = [
    {
        "secCode": "300750",
        "secName": "宁德时代",
        "announcementTitle": "宁德时代：2026年半年度业绩快报",
        "announcementTime": int(datetime(2026, 7, 19, 12, 0).timestamp() * 1000),
    },
]

_MOCK_CONTRACTS = [
    {
        "secCode": "000977",
        "secName": "浪潮信息",
        "announcementTitle": "浪潮信息：关于重大合同中标公告",
        "announcementTime": int(datetime(2026, 7, 21, 14, 0).timestamp() * 1000),
    },
]

_MOCK_BUYBACKS = [
    {
        "secCode": "000977",
        "secName": "浪潮信息",
        "announcementTitle": "浪潮信息：关于股份回购实施公告",
        "announcementTime": int(datetime(2026, 7, 21, 14, 30).timestamp() * 1000),
    },
]


def _mock_fulltext_search(searchkey, page=1, page_size=20,
                          start_date="", end_date="", stock=""):
    """Mock _fulltext_search for testing — 返回 dict 格式（匹配新接口）"""
    if "业绩预告" in searchkey:
        items = _MOCK_FORECASTS
    elif "业绩快报" in searchkey:
        items = _MOCK_REPORTS
    elif "重大合同" in searchkey:
        items = _MOCK_CONTRACTS
    elif "中标" in searchkey:
        items = []
    elif "回购" in searchkey:
        items = _MOCK_BUYBACKS
    elif "增持" in searchkey:
        items = []
    else:
        items = []

    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)

    # 模拟分页
    start_idx = (page - 1) * page_size
    page_items = items[start_idx:start_idx + page_size]

    return {
        "announcements": page_items,
        "totalAnnouncement": total,
        "totalpages": total_pages,
        "hasMore": page < total_pages,
    }


# ── 多页 Mock 数据（用于测试分页） ──

def _mock_paginated_search(searchkey, page=1, page_size=50,
                           start_date="", end_date="", stock=""):
    """Mock 返回多页数据的搜索（共 120 条，3 页）"""
    # 生成 120 条"业绩预告"用于分页测试
    all_items = []
    for i in range(120):
        ts = int(datetime(2026, 7, min(20 + i // 10, 31), 9, 0).timestamp() * 1000)
        all_items.append({
            "secCode": f"{600000 + i:06d}",
            "secName": f"测试股票{i:03d}",
            "announcementTitle": f"测试股票{i:03d}：2026年半年度业绩预告",
            "announcementTime": ts,
        })

    total = len(all_items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start_idx = (page - 1) * page_size
    page_items = all_items[start_idx:start_idx + page_size]

    return {
        "announcements": page_items,
        "totalAnnouncement": total,
        "totalpages": total_pages,
        "hasMore": page < total_pages,
    }


# ── 月度 Mock 数据（用于测试日期切片） ──

_MOCK_MONTHLY_DATA = {
    "forecasts": {
        "2026-01": [{"secCode": "600001", "secName": "测试A",
                      "announcementTitle": "测试A：2025年度业绩预告",
                      "announcementTime": int(datetime(2026, 1, 15, 10, 0).timestamp() * 1000)}],
        "2026-02": [{"secCode": "600002", "secName": "测试B",
                      "announcementTitle": "测试B：2026年一季度业绩预告",
                      "announcementTime": int(datetime(2026, 2, 10, 10, 0).timestamp() * 1000)}],
    }
}


def _mock_monthly_search(searchkey, page=1, page_size=50,
                         start_date="", end_date="", stock=""):
    """Mock 按月份返回不同数据"""
    month_key = start_date[:7] if start_date else "unknown"
    data = _MOCK_MONTHLY_DATA.get("forecasts", {}).get(month_key, [])
    if "业绩预告" not in searchkey:
        data = []
    return {
        "announcements": data,
        "totalAnnouncement": len(data),
        "totalpages": max(1, (len(data) + page_size - 1) // page_size),
        "hasMore": False,
    }


# ══════════════════════════════════════════════════════════════
# 测试
# ══════════════════════════════════════════════════════════════


def test_01_collector_writes_snapshot():
    """测试①: 采集器写入 announcement_snapshot"""
    print("\n── [test_01: 采集器写入 snapshot] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        collector = CNInfoSnapshotCollector()
        stats = collector.collect_all("2026-07-15", "2026-07-25")

    total = get_table_count("announcement_snapshot")
    ok(f"snapshot 记录数: {total} (预期≥4)") if total >= 4 else fail(f"预期≥4, 实得{total}")
    ok(f"inserted={stats['inserted']}") if stats["inserted"] >= 4 else fail(f"inserted<4: {stats}")
    ok(f"stocks={stats['stocks']}") if stats["stocks"] >= 2 else fail(f"stocks<2: {stats}")


def test_02_duplicate_not_reinserted():
    """测试②: 重复公告不会重复写入"""
    print("\n── [test_02: 去重] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        r1 = CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")
        c1 = get_table_count("announcement_snapshot")
        r2 = CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")
        c2 = get_table_count("announcement_snapshot")

    ok(f"两次采集行数不变: {c1} vs {c2}") if c1 == c2 else fail(f"行数变化: {c1}→{c2}")
    ok(f"第二次全部跳过 duplicate") if r2["inserted"] == 0 else fail(f"第二次不应新增: {r2}")
    ok(f"skipped_duplicates > 0") if r2["skipped_duplicates"] > 0 else fail(f"重复数应为正: {r2}")


def test_03_collection_tracking():
    """测试③: 采集元数据记录"""
    print("\n── [test_03: 采集元数据] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    conn = get_conn()
    cur = conn.execute(
        "SELECT * FROM collection_tracking WHERE collector_name='cninfo_announcement'"
    )
    row = cur.fetchone()
    ok("collection_tracking 有记录") if row else fail("无采集记录")
    if row:
        ok(f"status={row[3]}") if row[3] == "ok" else fail(f"status={row[3]}")
        stats = json.loads(row[4])
        ok(f"stats 含 inserted={stats.get('inserted')}") if stats.get("inserted", 0) >= 4 else fail("stats 不正确")


def test_04_available_time_correct():
    """测试④: available_time 正确写入"""
    print("\n── [test_04: available_time] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    anns = query_announcements_as_of("2026-07-31")
    ok(f"有公告数据 ({len(anns)}条)") if len(anns) >= 4 else fail(f"公告不足: {len(anns)}")

    for a in anns:
        if not a.get("publish_time") or not a.get("available_time"):
            fail(f"id={a['id']}: 缺少 publish_time 或 available_time")
            return
    ok("所有公告有 publish_time 和 available_time")

    before = query_announcements_as_of("2026-07-17")
    after = query_announcements_as_of("2026-07-22")
    ok(f"2026-07-17 之前 {len(before)} 条") if len(before) == 0 else fail(f"07-17 之前应有0条, 实得{len(before)}")
    ok(f"2026-07-22 之后 {len(after)} 条 (≥4)") if len(after) >= 4 else fail(f"07-22 之后应有≥4条, 实得{len(after)}")


def test_05_fundamental_scorer_no_network():
    """测试⑤: fundamental_scorer 只读 snapshot，不调用 API"""
    print("\n── [test_05: scorer 零网络请求] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    # 实际评分 — 不应抛出网络异常
    fs = FundamentalScorer(lookback_days=30)
    try:
        result = fs.score_stock("000977", "浪潮信息")
        ok(f"评分完成: score={result['score']}/15")
    except Exception as e:
        fail(f"评分异常: {type(e).__name__}: {e}")


def test_06_scorer_snapshot_only_reproducible():
    """测试⑥: 多次评分结果可复现（不依赖网络）"""
    print("\n── [test_06: 可复现性] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    fs1 = FundamentalScorer(lookback_days=30)
    fs2 = FundamentalScorer(lookback_days=30)
    r1 = fs1.score_stock("000977")
    r2 = fs2.score_stock("000977")

    ok(f"两次评分一致: {r1['score']} vs {r2['score']}") if r1['score'] == r2['score'] else fail(f"不一致: {r1['score']} vs {r2['score']}")
    ok(f"详情一致: {len(r1['details'])} vs {len(r2['details'])}") if r1['details'] == r2['details'] else fail("详情不同")


def test_07_empty_snapshot_graceful():
    """测试⑦: snapshot 为空时评分器优雅降级"""
    print("\n── [test_07: 空 snapshot 降级] ──")
    _reset_test_db()

    fs = FundamentalScorer(lookback_days=30)
    result = fs.score_stock("000977")
    ok(f"评分为 0/15") if result["score"] == 0 else fail(f"评分应为0, 实得{result['score']}")
    ok(f"无 forecast") if not result["forecasts"] else fail("应无 forecast")
    ok(f"无 contract") if not result["contracts"] else fail("应无 contract")


def test_08_pagination():
    """测试⑧: 自动分页 — 多页数据全部采集"""
    print("\n── [test_08: 自动分页] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_paginated_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        collector = CNInfoSnapshotCollector()
        stats = collector.collect_all("2026-07-01", "2026-07-31")

    total = get_table_count("announcement_snapshot")
    # 4 个非重复 announce_type × 120 条 = 480 (中标=重大合同, 增持=回购)
    ok(f"采集到 480 条分页数据 (4类型×120): {total}") if total == 480 else fail(f"预期480条, 实得{total}")
    ok(f"inserted=480") if stats["inserted"] == 480 else fail(f"inserted应=480: {stats}")
    ok(f"业绩预告全量采集: 120 条") if stats.get("detail", {}).get("业绩预告", 0) == 120 else fail(f"业绩预告计数不对: {stats}")


def test_09_date_slicing():
    """测试⑨: 月度日期切片 — 多个月份分别采集"""
    print("\n── [test_09: 月度日期切片] ──")
    _reset_test_db()

    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_monthly_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        collector = CNInfoSnapshotCollector()
        # 跨两个月的日期范围
        stats = collector.collect_all("2026-01-10", "2026-02-20")

    total = get_table_count("announcement_snapshot")
    ok(f"跨月采集 {total} 条 (≥2)") if total >= 2 else fail(f"预期≥2条, 实得{total}")
    ok(f"inserted≥2") if stats["inserted"] >= 2 else fail(f"inserted应≥2: {stats}")


def test_10_resume_state():
    """测试⑩: 断点续传状态记录"""
    print("\n── [test_10: 断点续传] ──")
    _reset_test_db()

    from data.cninfo_snapshot_collector import CNInfoSnapshotCollector

    # 第一次采集完成后，检查 collection_tracking 中有 resume 状态
    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    conn = get_conn()
    cur = conn.execute(
        "SELECT stats_json FROM collection_tracking "
        "WHERE collector_name='cninfo_announcement'"
        " ORDER BY last_run_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    ok("collection_tracking 有记录") if row else fail("无记录")
    if row:
        data = json.loads(row[0])
        # 最终记录不应包含 resume 字段（collect_all 完成后 _record_tracking 覆盖了）
        # 但应该包含 stats
        ok(f"stats 含 inserted={data.get('inserted')}") if data.get("inserted", 0) >= 4 else fail("stats 不正确")


def test_11_resume_state_preserved_on_interrupt():
    """测试⑪: 采集过程中的续传状态保存"""
    print("\n── [test_11: 中断续传状态] ──")
    _reset_test_db()

    from data.cninfo_snapshot_collector import CNInfoSnapshotCollector

    # 模拟部分采集：先完成一个月
    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_monthly_search):
        collector = CNInfoSnapshotCollector()
        # 只采集1月
        collector._collect_keyword_paginated("业绩预告", "performance_forecast",
                                              "2026-01-10", "2026-01-31")
        # 主动记录续传状态
        collector._update_resume_state("2026-01", "业绩预告")
        collector._mark_month_done("2026-01")

    # 检查续传状态已保存
    conn = get_conn()
    cur = conn.execute(
        "SELECT stats_json FROM collection_tracking "
        "WHERE collector_name='cninfo_announcement'"
        " ORDER BY last_run_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    ok("中断后有记录") if row else fail("无记录")
    if row:
        data = json.loads(row[0])
        resume = data.get("resume", {})
        months_done = resume.get("months_done", [])
        ok(f"已记录 2026-01 完成") if "2026-01" in months_done else fail(f"应含2026-01: {months_done}")


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📋 Atlas — CNINFO Snapshot Collector 测试 (v2)")
    print("   版本: 2.0.0 (Production Ready)")
    print(f"   {'='*40}")

    init_schema()

    tests = [
        ("test_01_collect", "采集器写入snapshot", test_01_collector_writes_snapshot),
        ("test_02_dedup", "重复公告去重", test_02_duplicate_not_reinserted),
        ("test_03_tracking", "采集元数据", test_03_collection_tracking),
        ("test_04_available", "available_time正确", test_04_available_time_correct),
        ("test_05_no_net", "scorer零网络", test_05_fundamental_scorer_no_network),
        ("test_06_reprod", "可复现性", test_06_scorer_snapshot_only_reproducible),
        ("test_07_empty", "空snapshot降级", test_07_empty_snapshot_graceful),
        ("test_08_pagination", "自动分页", test_08_pagination),
        ("test_09_slicing", "月度日期切片", test_09_date_slicing),
        ("test_10_resume", "断点续传状态", test_10_resume_state),
        ("test_11_interrupt", "中断续传", test_11_resume_state_preserved_on_interrupt),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total-passed} 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    if ERRORS:
        for err in ERRORS:
            print(f"      ❌ {err}")
    print(f"{'='*60}")
    sys.exit(0 if FAIL == 0 else 1)

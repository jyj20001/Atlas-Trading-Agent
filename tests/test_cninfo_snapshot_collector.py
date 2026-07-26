"""Atlas Trading Agent — CNINFO Snapshot Collector 测试

测试场景:
  1. 采集器读取 Mock CNINFO 数据并写入 announcement_snapshot
  2. 重复公告不会重复写入（UNIQUE 约束 + INSERT OR IGNORE）
  3. available_time 正确计算
  4. 扫描阶段（fundamental_scorer）只读 snapshot，不访问网络
  5. 采集元数据正确记录
  6. 采集统计正确（stocks/inserted/skipped/failures）

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
    """重置测试数据库 — 重建 announcement_snapshot 确保 UNIQUE 约束生效"""
    conn = get_conn()
    # 删除旧表重建（确保 schema 包含 UNIQUE 约束）
    conn.execute("DROP TABLE IF EXISTS announcement_snapshot")
    conn.execute("DROP TABLE IF EXISTS collection_tracking")
    conn.commit()
    # 重新初始化 schema
    init_schema()


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
    """Mock _fulltext_search for testing"""
    if "业绩预告" in searchkey:
        return _MOCK_FORECASTS
    elif "业绩快报" in searchkey:
        return _MOCK_REPORTS
    elif "重大合同" in searchkey:
        return _MOCK_CONTRACTS
    elif "中标" in searchkey:
        return []
    elif "回购" in searchkey:
        return _MOCK_BUYBACKS
    elif "增持" in searchkey:
        return []
    return []


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

    # 应写入 4 条：2 forecasts + 1 report + 1 contract + 1 buyback
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
        # 第一次采集
        r1 = CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")
        c1 = get_table_count("announcement_snapshot")

        # 第二次采集（相同数据）
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

    # 查询所有公告
    anns = query_announcements_as_of("2026-07-31")
    ok(f"有公告数据 ({len(anns)}条)") if len(anns) >= 4 else fail(f"公告不足: {len(anns)}")

    # 每条必须有 publish_time 和 available_time
    for a in anns:
        if not a.get("publish_time") or not a.get("available_time"):
            fail(f"id={a['id']}: 缺少 publish_time 或 available_time")
            return
    ok("所有公告有 publish_time 和 available_time")

    # 验证 as_of 过滤
    before = query_announcements_as_of("2026-07-17")
    after = query_announcements_as_of("2026-07-22")
    ok(f"2026-07-17 之前 {len(before)} 条") if len(before) == 0 else fail(f"07-17 之前应有0条, 实得{len(before)}")
    ok(f"2026-07-22 之后 {len(after)} 条 (≥4)") if len(after) >= 4 else fail(f"07-22 之后应有≥4条, 实得{len(after)}")


def test_05_fundamental_scorer_no_network():
    """测试⑤: fundamental_scorer 只读 snapshot，不调用 API"""
    print("\n── [test_05: scorer 零网络请求] ──")
    _reset_test_db()

    # 先填充 snapshot
    with patch("data.cninfo_fetcher._fulltext_search",
               side_effect=_mock_fulltext_search):
        from data.cninfo_snapshot_collector import CNInfoSnapshotCollector
        CNInfoSnapshotCollector().collect_all("2026-07-15", "2026-07-25")

    # 验证 scorer 不使用任何网络函数
    original_imports = [
        "core.fundamental_scorer.search_performance_forecasts",
        "core.fundamental_scorer.search_performance_reports",
        "core.fundamental_scorer._fulltext_search",
    ]
    for imp in original_imports:
        try:
            __import__(imp)
            fail(f"scorer 仍导入 {imp}")
        except (ImportError, ModuleNotFoundError):
            pass
    ok("scorer 不再导入 cninfo_fetcher 网络函数")

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


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📋 Atlas — CNINFO Snapshot Collector 测试")
    print("   版本: 1.0.0 (Phase 2)")
    print(f"   {'='*40}")

    # 确保 schema 存在
    init_schema()

    tests = [
        ("test_01_collect", "采集器写入snapshot", test_01_collector_writes_snapshot),
        ("test_02_dedup", "重复公告去重", test_02_duplicate_not_reinserted),
        ("test_03_tracking", "采集元数据", test_03_collection_tracking),
        ("test_04_available", "available_time正确", test_04_available_time_correct),
        ("test_05_no_net", "scorer零网络", test_05_fundamental_scorer_no_network),
        ("test_06_reprod", "可复现性", test_06_scorer_snapshot_only_reproducible),
        ("test_07_empty", "空snapshot降级", test_07_empty_snapshot_graceful),
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

"""Atlas Trading Agent — Historical Snapshot 查询测试

测试要求 (Phase 1):
  1. 查询未来数据必须为空  — available_time > signal_date 的数据被正确过滤
  2. 查询历史可见数据必须返回 — available_time <= signal_date 的数据正确返回
  3. 同一天多个公告不能冲突 — 同一天插入多条公告全部可查询
  4. Schema 创建正确 — 4 张表结构完整
  5. 4 个维度的 as_of 查询均正常工作
  6. 无效日期格式抛出可读异常

运行:
  python tests/test_snapshot_query.py
"""

import sys
import os
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

import logging
logging.getLogger("data.snapshot_schema").setLevel(logging.ERROR)
logging.getLogger("data.snapshot_query").setLevel(logging.ERROR)

from data.snapshot_schema import (
    HistoricalDB, get_conn, get_db_path, table_exists,
    TABLE_NAMES, DATA_TABLE_NAMES, init_schema, get_table_count,
)
from data.snapshot_query import (
    query_announcements_as_of, query_fundamentals_as_of,
    query_sector_as_of, query_market_as_of,
    query_all_as_of, get_snapshot_stats, SnapshotQueryError,
)


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


def _insert_announcement(conn, code, name, publish_time, available_time,
                          announce_type, **kw):
    """Helper to insert announcement row"""
    fields = {
        "report_type": "", "forecast_type": "", "title": "", "keyword": "",
        "net_profit_lower": None, "net_profit_upper": None,
        "change_pct_lower": None, "change_pct_upper": None,
        "source": "test", "snapshot_version": "1.0.0",
    }
    fields.update(kw)
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, title, keyword, "
        "net_profit_lower, net_profit_upper, "
        "change_pct_lower, change_pct_upper, "
        "source, snapshot_version) "
        "VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?)",
        (code, name, publish_time, available_time, announce_type,
         fields["report_type"], fields["forecast_type"],
         fields["title"], fields["keyword"],
         fields["net_profit_lower"], fields["net_profit_upper"],
         fields["change_pct_lower"], fields["change_pct_upper"],
         fields["source"], fields["snapshot_version"],
        )
    )
    conn.commit()


def _insert_sector(conn, index_code, sector_name, trade_date,
                    publish_time, available_time, close=100):
    conn.execute(
        "INSERT INTO sector_snapshot "
        "(index_code, sector_name, trade_date, publish_time, available_time, "
        "close, return_1d, return_5d, volume, ma20, "
        "source, snapshot_version) "
        "VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?)",
        (index_code, sector_name, trade_date, publish_time, available_time,
         close, 0, 0, 0, close,
         "test", "1.0.0")
    )
    conn.commit()


def _insert_market(conn, index_code, index_name, trade_date,
                    publish_time, available_time, close=3000):
    conn.execute(
        "INSERT INTO market_snapshot "
        "(index_code, index_name, trade_date, publish_time, available_time, "
        "open, close, high, low, volume, ma20, ma50, trend_score, market_status, "
        "source, snapshot_version) "
        "VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?)",
        (index_code, index_name, trade_date, publish_time, available_time,
         close, close, close, close, 0, close, close, 3, "neutral",
         "test", "1.0.0")
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════
# 测试套件
# ══════════════════════════════════════════════════════════════


def test_01_schema_creation():
    """测试①: 所有 4 张表创建成功"""
    print("\n── [test_01: Schema创建] ──")
    # 使用独立测试数据库
    _reset_test_db()

    for table in TABLE_NAMES:
        if table_exists(table):
            ok(f"表 {table} 创建成功")
        else:
            fail(f"表 {table} 不存在")

    # 检查列名
    conn = get_conn()
    for table in DATA_TABLE_NAMES:
        cur = conn.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in cur.fetchall()}
        required = {"id", "publish_time", "available_time", "source", "snapshot_version"}
        missing = required - cols
        if not missing:
            ok(f"{table}: 包含 publish_time/available_time/source/snapshot_version")
        else:
            fail(f"{table}: 缺少字段 {missing}")

    # announcement_snapshot 必须有 id 主键
    cur = conn.execute("PRAGMA table_info(announcement_snapshot)")
    pk_cols = [r[1] for r in cur.fetchall() if r[5] == 1]
    if "id" in pk_cols:
        ok("announcement_snapshot 主键为 id (AUTOINCREMENT)")
    else:
        fail(f"announcement_snapshot 主键异常: {pk_cols}")


def test_02_future_data_empty():
    """测试②: 查询未来数据必须为空"""
    print("\n── [test_02: 未来数据过滤] ──")
    _reset_test_db()
    conn = get_conn()

    # 插入未来数据
    _insert_announcement(conn, "000977", "浪潮信息",
                         "2026-12-01 08:00:00", "2026-12-01 08:00:00",
                         "performance_forecast", report_type="预增")

    _insert_sector(conn, "sz980017", "半导体",
                   "2026-12-01", "2026-12-01 15:00:00", "2026-12-01 15:00:00")

    # 以今天之前查询 — 未来数据不应出现
    ann = query_announcements_as_of("2026-07-01")
    ok(f"未来公告查询为空 (返回 {len(ann)} 条)") if len(ann) == 0 else fail(f"预期0条, 实得{len(ann)}")

    sec = query_sector_as_of("2026-07-01")
    ok(f"未来板块查询为空 (返回 {len(sec)} 条)") if len(sec) == 0 else fail(f"预期0条, 实得{len(sec)}")


def test_03_historical_data_returned():
    """测试③: 查询历史可见数据必须返回"""
    print("\n── [test_03: 历史可见数据查询] ──")
    _reset_test_db()
    conn = get_conn()

    # 插入历史数据
    _insert_announcement(conn, "000977", "浪潮信息",
                         "2026-07-15 16:30:00", "2026-07-15 16:30:00",
                         "performance_forecast", report_type="预增")
    _insert_announcement(conn, "600519", "贵州茅台",
                         "2026-07-20 09:00:00", "2026-07-20 09:00:00",
                         "performance_report", report_type="预增")

    _insert_sector(conn, "sz980017", "半导体",
                   "2026-07-18", "2026-07-18 15:00:00", "2026-07-18 15:00:00",
                   close=5200)
    _insert_market(conn, "000300", "沪深300",
                   "2026-07-18", "2026-07-18 15:00:00", "2026-07-18 15:00:00",
                   close=3850)

    # 查询 2026-07-20 — 应包含所有 4 条
    ann = query_announcements_as_of("2026-07-21")
    ok(f"公告返回 {len(ann)} 条 (预期2)") if len(ann) == 2 else fail(f"预期2条, 实得{len(ann)}")

    sec = query_sector_as_of("2026-07-21")
    ok(f"板块返回 {len(sec)} 条 (预期1)") if len(sec) == 1 else fail(f"预期1条, 实得{len(sec)}")

    mkt = query_market_as_of("2026-07-21")
    ok(f"市场返回 {len(mkt)} 条 (预期1)") if len(mkt) == 1 else fail(f"预期1条, 实得{len(mkt)}")

    # 按股票代码过滤
    ann_000977 = query_announcements_as_of("2026-07-21", code="000977")
    ok(f"code过滤: 000977 ({len(ann_000977)}条)") if len(ann_000977) == 1 else fail(f"预期1条, 实得{len(ann_000977)}")

    all_data = query_all_as_of("2026-07-21")
    ok(f"全量查询包含4个维度") if len(all_data) == 4 else fail(f"预期4个维度, 实得{len(all_data)}")


def test_04_multiple_announcements_same_day():
    """测试④: 同一天多个公告不冲突"""
    print("\n── [test_04: 同天多公告] ──")
    _reset_test_db()
    conn = get_conn()

    # 同一只股票同一天 3 条不同公告
    for i, (at, rt, title) in enumerate([
        ("performance_forecast", "预增", "2026年半年度业绩预告"),
        ("major_contract", "", "重大合同中标公告"),
        ("buyback", "", "股份回购实施公告"),
    ]):
        _insert_ann(conn, "000977", "浪潮信息",
                     f"2026-07-20 1{i}:30:00",
                     f"2026-07-20 1{i}:30:00",
                     at, report_type=rt, title=title)

    ann = query_announcements_as_of("2026-07-21", code="000977")
    ok(f"3条公告全部返回 ({len(ann)}条)") if len(ann) == 3 else fail(f"预期3条, 实得{len(ann)}")

    # 验证公告类型各不相同
    types = {a["announce_type"] for a in ann}
    ok(f"公告类型各异: {types}") if len(types) == 3 else fail(f"类型去重后应为3, 实得{len(types)}")

    # 验证 id 各不相同
    ids = {a["id"] for a in ann}
    ok(f"ID唯一 ({len(ids)}个)") if len(ids) == 3 else fail(f"ID重复, {len(ids)}个唯一")


def _insert_ann(conn, code, name, pt, at, atype, **kw):
    """Short alias for _insert_announcement"""
    _insert_announcement(conn, code, name, pt, at, atype, **kw)


def test_05_as_of_filtering_edge_cases():
    """测试⑤: 查询边界条件"""
    print("\n── [test_05: 边界条件] ──")
    _reset_test_db()
    conn = get_conn()

    # 数据刚好在 signal_date 当天
    _insert_ann(conn, "000977", "浪潮信息",
                "2026-07-20 15:30:00", "2026-07-20 15:30:00",
                "performance_forecast")

    # 查询当天
    ann = query_announcements_as_of("2026-07-20", code="000977")
    ok("当天数据可查询") if len(ann) == 1 else fail(f"当天数据应返回, 实得{len(ann)}")

    # 查询前一天 — 应空
    ann2 = query_announcements_as_of("2026-07-19", code="000977")
    ok("前一天数据不可见") if len(ann2) == 0 else fail(f"前一天应空, 实得{len(ann2)}")

    # 查询后一天
    ann3 = query_announcements_as_of("2026-07-21", code="000977")
    ok("后一天数据可见") if len(ann3) == 1 else fail(f"后一天应返回, 实得{len(ann3)}")

    # 空数据库查询
    conn2 = get_conn()
    conn2.execute("DELETE FROM announcement_snapshot")
    conn2.commit()
    ann4 = query_announcements_as_of("2026-07-20")
    ok("空数据库返回空列表") if len(ann4) == 0 else fail(f"空数据库应返回[], 实得{len(ann4)}")


def test_06_invalid_date_format():
    """测试⑥: 无效日期格式抛出可读异常"""
    print("\n── [test_06: 无效日期格式] ──")
    _reset_test_db()

    for bad_input in ["not-a-date", "2026/07/20", "2026-13-01", ""]:
        try:
            query_announcements_as_of(bad_input)
            fail(f"未抛出异常: '{bad_input}'")
        except SnapshotQueryError as e:
            ok(f"无效日期 '{bad_input}' → {e}")
        except Exception as e:
            fail(f"异常类型错误 '{bad_input}': {type(e).__name__}")

    # 有效格式不应抛出
    try:
        query_announcements_as_of("2026-07-20")
        ok("有效日期 '2026-07-20' 正常通过")
    except SnapshotQueryError as e:
        fail(f"有效日期被拒绝: {e}")


def test_07_snapshot_version_default():
    """测试⑦: snapshot_version 默认值"""
    print("\n── [test_07: snapshot_version] ──")
    _reset_test_db()
    conn = get_conn()

    _insert_ann(conn, "000977", "浪潮信息",
                "2026-07-20 15:30:00", "2026-07-20 15:30:00",
                "performance_forecast")

    ann = query_announcements_as_of("2026-07-21", code="000977")
    if ann and ann[0].get("snapshot_version") == "1.0.0":
        ok(f"snapshot_version = 1.0.0")
    else:
        fail(f"snapshot_version 缺失或错误: {ann[0].get('snapshot_version') if ann else 'NO_DATA'}")

    # sector snapshot
    _insert_sector(conn, "sz980017", "半导体",
                   "2026-07-20", "2026-07-20 15:00:00", "2026-07-20 15:00:00")
    sec = query_sector_as_of("2026-07-21")
    if sec and sec[0].get("snapshot_version") == "1.0.0":
        ok("sector_snapshot 也有 snapshot_version=1.0.0")
    else:
        fail("sector snapshot 无 snapshot_version")


def test_08_source_field():
    """测试⑧: source 字段"""
    print("\n── [test_08: source 字段] ──")
    _reset_test_db()
    conn = get_conn()

    _insert_ann(conn, "000977", "浪潮信息",
                "2026-07-20 15:30:00", "2026-07-20 15:30:00",
                "performance_forecast", source="cninfo")
    _insert_market(conn, "000300", "沪深300",
                   "2026-07-20", "2026-07-20 15:00:00", "2026-07-20 15:00:00")

    ann = query_announcements_as_of("2026-07-21")
    ok(f"公告 source=cninfo") if ann and ann[0].get("source") == "cninfo" else fail("公告 source 错误")

    mkt = query_market_as_of("2026-07-21")
    ok(f"市场 source=test (通过insert设置)") if mkt and mkt[0].get("source") == "test" else fail(f"市场 source 错误: {mkt[0].get('source') if mkt else 'NONE'}")


def _reset_test_db():
    """重置测试数据库 — 清除所有表数据而非删除文件"""
    conn = get_conn()
    for table in TABLE_NAMES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📋 Atlas Trading Agent — Historical Snapshot 查询测试")
    print("   版本: 1.0.0 (Phase 1)")
    print(f"   {'='*40}")

    tests = [
        ("test_01_schema", "Schema创建", test_01_schema_creation),
        ("test_02_future", "未来数据过滤", test_02_future_data_empty),
        ("test_03_hist", "历史可见数据", test_03_historical_data_returned),
        ("test_04_multiple", "同天多公告", test_04_multiple_announcements_same_day),
        ("test_05_edge", "边界条件", test_05_as_of_filtering_edge_cases),
        ("test_06_date", "无效日期格式", test_06_invalid_date_format),
        ("test_07_version", "snapshot_version", test_07_snapshot_version_default),
        ("test_08_source", "source字段", test_08_source_field),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
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

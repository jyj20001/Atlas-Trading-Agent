"""Atlas Trading Agent — No Look-ahead 验证测试

5 项 Look-ahead Bias 检测：

  1. 公告日期 > signal_date → 不可读取
  2. 财报发布日期 > signal_date → 不可读取
  3. 板块数据未来交易日 → 不可读取
  4. 市场指数未来数据 → 不可读取
  5. 同一天：上午信号不能读取下午公告

所有测试使用 Mock 数据，禁止访问真实网络。

禁止:
  - 修改评分体系
  - 修改 130 分权重
  - 修改 Buy Stop 参数
"""

import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

logging.disable(logging.CRITICAL)

from data.snapshot_schema import (
    get_conn, init_schema, TABLE_NAMES, SNAPSHOT_VERSION,
)
from data.snapshot_query import (
    query_announcements_as_of,
    query_fundamentals_as_of,
    query_sector_as_of,
    query_market_as_of,
    SnapshotQueryError,
)

PASS = 0
FAIL = 0

def ok(msg):
    global PASS; PASS += 1; print(f"  ✅ {msg}")
def fail(msg):
    global FAIL; FAIL += 1; print(f"  ❌ {msg}")

def _reset():
    conn = get_conn()
    for t in TABLE_NAMES:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


# ══════════════════════════════════════════════════════════════
# Test 1: 公告日期 > signal_date
# ══════════════════════════════════════════════════════════════

def test_01_ann_future_date():
    """公告日期 (2026-12-01) > signal_date (2026-07-20) → 不可读取"""
    print("\n── [test_01: 公告日期 > signal_date] ──")
    _reset()
    conn = get_conn()

    # 插入一条未来公告
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000977", "浪潮信息",
         "2026-12-01 08:00:00", "2026-12-01 08:00:00",
         "performance_forecast", "预增", "业绩预告",
         "test", SNAPSHOT_VERSION)
    )
    # 插入一条过去公告（验证过滤只针对未来）
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600519", "贵州茅台",
         "2026-07-15 08:00:00", "2026-07-15 08:00:00",
         "performance_forecast", "预增", "业绩预告",
         "test", SNAPSHOT_VERSION)
    )
    conn.commit()

    # signal_date=2026-07-20 → 未来公告不可见
    rows = query_announcements_as_of("2026-07-20", code="000977")
    ok("未来公告不可见 (0条)") if len(rows) == 0 else fail(f"预期0条, 实得{len(rows)}")

    # 验证过去公告仍然可见
    rows2 = query_announcements_as_of("2026-07-20", code="600519")
    ok("过去公告可见 (1条)") if len(rows2) == 1 else fail(f"预期1条, 实得{len(rows2)}")


# ══════════════════════════════════════════════════════════════
# Test 2: 财报发布日期 > signal_date
# ══════════════════════════════════════════════════════════════

def test_02_fundamental_future_date():
    """财报发布日期 (2026-12-01) > signal_date (2026-07-20) → 不可读取"""
    print("\n── [test_02: 财报日期 > signal_date] ──")
    _reset()
    conn = get_conn()

    # 插入未来财报
    conn.execute(
        "INSERT INTO fundamental_snapshot "
        "(code, name, fiscal_period, publish_time, available_time, "
        "revenue, net_profit, roe, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000977", "浪潮信息", "2026Q2",
         "2026-12-01 08:00:00", "2026-12-01 08:00:00",
         100, 20, 0.15, "test", SNAPSHOT_VERSION)
    )
    # 插入过去财报
    conn.execute(
        "INSERT INTO fundamental_snapshot "
        "(code, name, fiscal_period, publish_time, available_time, "
        "revenue, net_profit, roe, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600519", "贵州茅台", "2026Q1",
         "2026-04-30 08:00:00", "2026-04-30 08:00:00",
         200, 50, 0.20, "test", SNAPSHOT_VERSION)
    )
    conn.commit()

    # signal_date=2026-07-20 → 未来财报不可见
    rows = query_fundamentals_as_of("2026-07-20", code="000977")
    ok("未来财报不可见 (0条)") if len(rows) == 0 else fail(f"预期0条, 实得{len(rows)}")

    # 过去财报可见
    rows2 = query_fundamentals_as_of("2026-07-20", code="600519")
    ok("过去财报可见 (1条)") if len(rows2) == 1 else fail(f"预期1条, 实得{len(rows2)}")


# ══════════════════════════════════════════════════════════════
# Test 3: 板块数据未来交易日
# ══════════════════════════════════════════════════════════════

def test_03_sector_future_trade_date():
    """板块数据未来交易日 (2026-12-01) > signal_date (2026-07-20) → 不可读取"""
    print("\n── [test_03: 板块未来交易日] ──")
    _reset()
    conn = get_conn()

    # 插入未来板块数据
    conn.execute(
        "INSERT INTO sector_snapshot "
        "(index_code, sector_name, trade_date, publish_time, available_time, "
        "close, return_1d, return_5d, volume, ma20, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sz980017", "半导体", "2026-12-01",
         "2026-12-01 15:00:00", "2026-12-01 15:00:00",
         5000, 1.5, 5.0, 1e8, 4800, "test", SNAPSHOT_VERSION)
    )
    # 插入过去板块数据
    conn.execute(
        "INSERT INTO sector_snapshot "
        "(index_code, sector_name, trade_date, publish_time, available_time, "
        "close, return_1d, return_5d, volume, ma20, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("sz980017", "半导体", "2026-07-17",
         "2026-07-17 15:00:00", "2026-07-17 15:00:00",
         4800, -0.5, 2.0, 1e8, 4750, "test", SNAPSHOT_VERSION)
    )
    conn.commit()

    # signal_date=2026-07-20 → 未来板块不可见
    rows = query_sector_as_of("2026-07-20", index_code="sz980017")
    ok("未来板块不可见") if len(rows) == 1 else fail(f"预期1条(过去), 实得{len(rows)}")
    ok("返回的是过去数据") if rows and rows[0]["trade_date"] == "2026-07-17" else fail("返回了未来数据")
    ok("return_5d来自过去") if rows and rows[0]["return_5d"] == 2.0 else fail("return_5d不正确")


# ══════════════════════════════════════════════════════════════
# Test 4: 市场指数未来数据
# ══════════════════════════════════════════════════════════════

def test_04_market_future_date():
    """市场指数未来数据 (2026-12-01) > signal_date (2026-07-20) → 不可读取"""
    print("\n── [test_04: 市场指数未来数据] ──")
    _reset()
    conn = get_conn()

    # 插入未来市场数据
    conn.execute(
        "INSERT INTO market_snapshot "
        "(index_code, index_name, trade_date, publish_time, available_time, "
        "open, close, high, low, volume, ma20, ma50, trend_score, market_status, "
        "source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000300", "沪深300", "2026-12-01",
         "2026-12-01 15:00:00", "2026-12-01 15:00:00",
         4200, 4250, 4260, 4180, 1e9, 4200, 4150, 5, "bull",
         "test", SNAPSHOT_VERSION)
    )
    # 插入过去市场数据
    conn.execute(
        "INSERT INTO market_snapshot "
        "(index_code, index_name, trade_date, publish_time, available_time, "
        "open, close, high, low, volume, ma20, ma50, trend_score, market_status, "
        "source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000300", "沪深300", "2026-07-17",
         "2026-07-17 15:00:00", "2026-07-17 15:00:00",
         3800, 3850, 3860, 3780, 1e9, 3820, 3800, 3, "neutral",
         "test", SNAPSHOT_VERSION)
    )
    conn.commit()

    # signal_date=2026-07-20 → 未来市场不可见
    rows = query_market_as_of("2026-07-20", index_code="000300")
    ok("未来市场不可见") if len(rows) == 1 else fail(f"预期1条(过去), 实得{len(rows)}")
    ok("返回过去数据") if rows and rows[0]["trade_date"] == "2026-07-17" else fail("返回了未来数据")
    ok("market_status来自过去") if rows and rows[0]["market_status"] == "neutral" else fail(f"状态错误: {rows[0]['market_status']}")


# ══════════════════════════════════════════════════════════════
# Test 5: 同一天 — 上午信号不能读取下午公告
# ══════════════════════════════════════════════════════════════

def test_05_morning_signal_afternoon_ann():
    """同一天内: 上午信号 (09:30) 不能读取下午 (14:30) 公告"""
    print("\n── [test_05: 上午信号 vs 下午公告] ──")
    _reset()
    conn = get_conn()

    # 插入下午发布的公告 (available_time=2026-07-20 14:30:00)
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000977", "浪潮信息",
         "2026-07-20 14:30:00", "2026-07-20 14:30:00",
         "performance_forecast", "预增", "业绩预告",
         "test", SNAPSHOT_VERSION)
    )
    # 插入上午发布的公告 (available_time=2026-07-20 09:00:00)
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("600519", "贵州茅台",
         "2026-07-20 09:00:00", "2026-07-20 09:00:00",
         "performance_forecast", "预增", "业绩预告",
         "test", SNAPSHOT_VERSION)
    )
    conn.commit()

    # 上午信号 (09:30) → 下午公告 (14:30) 不可见
    rows = query_announcements_as_of(
        "2026-07-20", code="000977",
        signal_datetime="2026-07-20 09:30:00"
    )
    ok("上午信号看不到下午公告 (0条)") if len(rows) == 0 else fail(f"预期0条, 实得{len(rows)}")

    # 上午信号 (09:30) → 上午公告 (09:00) 可见
    rows2 = query_announcements_as_of(
        "2026-07-20", code="600519",
        signal_datetime="2026-07-20 09:30:00"
    )
    ok("上午信号可见上午公告 (1条)") if len(rows2) == 1 else fail(f"预期1条, 实得{len(rows2)}")

    # 下午信号 (15:00收盘后) → 两条都可见
    rows3 = query_announcements_as_of(
        "2026-07-20",
        signal_datetime="2026-07-20 15:00:00"
    )
    ok("收盘后两条都可见 (2条)") if len(rows3) == 2 else fail(f"预期2条, 实得{len(rows3)}")

    # 日期级查询（无 signal_datetime）→ 两条都可见（默认日期级）
    rows4 = query_announcements_as_of("2026-07-20")
    ok("日期级查询两条都可见 (2条)") if len(rows4) == 2 else fail(f"预期2条, 实得{len(rows4)}")

    # 验证前一天收盘后 → 只看前一天数据
    conn.execute("DELETE FROM announcement_snapshot")
    # 插入下午的数据
    conn.execute(
        "INSERT INTO announcement_snapshot "
        "(code, name, publish_time, available_time, announce_type, "
        "report_type, forecast_type, source, snapshot_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("000977", "浪潮信息",
         "2026-07-19 14:30:00", "2026-07-19 14:30:00",
         "performance_forecast", "预增", "业绩预告",
         "test", SNAPSHOT_VERSION)
    )
    conn.commit()
    # 7/20 早上 → 7/19 下午公告应可见
    rows5 = query_announcements_as_of(
        "2026-07-20", code="000977",
        signal_datetime="2026-07-20 09:30:00"
    )
    ok("上午信号可见前一天下午公告 (1条)") if len(rows5) == 1 else fail(f"预期1条, 实得{len(rows5)}")


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📋 Atlas — No Look-ahead 验证测试 (5项)")
    print("   版本: 1.0.0 (Phase 3-1)")
    print(f"   {'='*40}")

    init_schema()

    tests = [
        ("test_01_ann_future", "公告日期 > signal_date", test_01_ann_future_date),
        ("test_02_fund_future", "财报日期 > signal_date", test_02_fundamental_future_date),
        ("test_03_sector_future", "板块未来交易日", test_03_sector_future_trade_date),
        ("test_04_market_future", "市场指数未来数据", test_04_market_future_date),
        ("test_05_morning_signal", "上午信号 vs 下午公告", test_05_morning_signal_afternoon_ann),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total-passed} 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    print(f"{'='*60}")
    sys.exit(0 if FAIL == 0 else 1)

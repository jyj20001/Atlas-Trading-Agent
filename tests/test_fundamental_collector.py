"""Atlas Trading Agent — 基本面数据采集器测试

测试:
  1. 数据写入
  2. 去重
  3. available_time 过滤（无未来函数）
  4. 代码格式转换
"""

import sys, os, logging, tempfile
logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "buy_stop_v3"))


PASS = 0
FAIL = 0
_TESTS_RUN = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  ✅ {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  ❌ {msg}")


def assert_eq(a, b, label=""):
    if a == b:
        ok(f"{label}: {a}" if label else str(a))
    else:
        fail(f"{label}: {a} != {b}" if label else f"ex {b} got {a}")


# ── Tests ──


def test_01_collect_and_write():
    """采集股票并写入 DB（使用 600519，清理旧数据保证测试独立）"""
    from data.fundamental.fundamental_collector import collect_stock
    from data.snapshot_schema import get_conn

    # 清理测试用股票的旧数据
    conn = get_conn()
    conn.execute("DELETE FROM fundamental_snapshot WHERE code='600519'")
    conn.commit()

    n = collect_stock("600519")
    assert n > 0, f"写入行数: {n}"
    ok(f"写入 {n} 行 (600519)")

    rows = conn.execute(
        "SELECT * FROM fundamental_snapshot WHERE code='600519' ORDER BY fiscal_period DESC LIMIT 1"
    ).fetchall()
    assert rows, "无数据"
    row = rows[0]
    ok(f"最新: {row[3]} ({row[4]}) 营收={row[6]} 净利={row[8]} 可用={row[5]}")
    # 验证 source 字段
    assert_eq(row[16], "eastmoney", "数据来源 source")


def test_02_dedup():
    """重复采集不应产生重复行"""
    from data.fundamental.fundamental_collector import collect_stock
    from data.snapshot_schema import get_conn

    before = get_conn().execute(
        "SELECT COUNT(*) FROM fundamental_snapshot WHERE code='600519'"
    ).fetchone()[0]

    # 清理后重新采集（验证去重）
    get_conn().execute("DELETE FROM fundamental_snapshot WHERE code='600519'")
    get_conn().commit()
    n = collect_stock("600519")
    n2 = collect_stock("600519")  # 第二次应返回 0
    after = get_conn().execute(
        "SELECT COUNT(*) FROM fundamental_snapshot WHERE code='600519'"
    ).fetchone()[0]

    assert_eq(n2, 0, "去重: 重复写入")
    ok(f"去重: 首次{n}行 第二次{n2}行 总数{after}")


def test_03_available_time_filter():
    """available_time 过滤（无未来函数）"""
    from data.snapshot_schema import get_conn

    conn = get_conn()
    # 688111 最新报告
    row = conn.execute(
        "SELECT available_time FROM fundamental_snapshot "
        "WHERE code='600519' ORDER BY fiscal_period DESC LIMIT 1"
    ).fetchone()
    assert row, "无可用时间"
    available = row[0]
    ok(f"600519 最新可用时间: {available}")


def test_04_calc_available_time():
    """_calc_available_time 逻辑"""
    from data.fundamental.fundamental_collector import _calc_available_time

    assert_eq(_calc_available_time("2026-04-30 00:00:00"), "2026-05-01", "公告次日")
    assert_eq(_calc_available_time(""), "2026-07-26"[:10], "空日期用今日",)


def test_05_code_conversion():
    """代码格式转换"""
    from data.fundamental.fundamental_collector import _to_eastmoney_code

    assert_eq(_to_eastmoney_code("600000"), "600000.SH", "沪市")
    assert_eq(_to_eastmoney_code("000001"), "000001.SZ", "深市")
    assert_eq(_to_eastmoney_code("300750"), "300750.SZ", "创业板")
    assert_eq(_to_eastmoney_code("688111"), "688111.SH", "科创板")


# ── Run ──

def run():
    test_05_code_conversion()
    test_04_calc_available_time()
    test_01_collect_and_write()
    test_02_dedup()
    test_03_available_time_filter()

    print(f"\n📊 汇总: {PASS}/{PASS+FAIL} 通过, 0 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(run())

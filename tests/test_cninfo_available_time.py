"""Atlas Trading Agent — cninfo _calc_available_time 测试

验证交易时段/非交易时段 available_time 计算逻辑。
"""

import sys, os, logging
logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "buy_stop_v3"))

PASS = 0
FAIL = 0

def ok(msg):
    global PASS; PASS += 1; print(f"  ✅ {msg}")
def fail(msg):
    global FAIL; FAIL += 1; print(f"  ❌ {msg}")
def assert_eq(a, b, label=""):
    if a == b:
        ok(f"{label}: {a}")
    else:
        fail(f"{label}: ex={b} got={a}")


def test_trading_hours():
    from data.cninfo_snapshot_collector import _calc_available_time

    # 盘中发布 (09:30-15:00) → available_time = publish_time
    assert_eq(_calc_available_time("2026-04-30 09:30:00"), "2026-04-30 09:30:00", "盘中: 09:30")
    assert_eq(_calc_available_time("2026-04-30 10:00:00"), "2026-04-30 10:00:00", "盘中: 10:00")
    assert_eq(_calc_available_time("2026-04-30 14:59:59"), "2026-04-30 14:59:59", "盘中: 14:59")

    # 非交易时段发布 → next day
    assert_eq(_calc_available_time("2026-04-30 15:00:00"), "2026-05-01", "盘后: 15:00 整")
    assert_eq(_calc_available_time("2026-04-30 15:01:00"), "2026-05-01", "盘后: 15:01")
    assert_eq(_calc_available_time("2026-04-30 07:00:00"), "2026-05-01", "盘前: 07:00")
    assert_eq(_calc_available_time("2026-04-30 09:29:59"), "2026-05-01", "盘前: 09:29")

    # 空/无效输入
    from datetime import date
    assert_eq(_calc_available_time("")[:10], date.today().isoformat()[:10], "空输入: 当日")
    assert_eq(_calc_available_time("2026-04-30"), "2026-04-30", "仅日期无时分: 原样返回")


def run():
    print("=" * 60)
    print("  _calc_available_time() 测试")
    print("=" * 60)
    test_trading_hours()
    print(f"\n📊 汇总: {PASS}/{PASS+FAIL} 通过, 0 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(run())

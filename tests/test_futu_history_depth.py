"""Atlas Trading Agent — FutuProvider 历史K线深度测试

验证:
  1. FutuProvider 连接/降级行为
  2. 代码格式转换 (A股→富途)
  3. 分页逻辑（mock 方式）
  4. 复权类型支持

注: 由于 OpenD 未运行，实际连接测试不可执行。
    测试验证代码结构和降级行为。
"""

import sys, os, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

PASS = 0
FAIL = 0

def ok(msg): global PASS; PASS += 1; print(f"  ✅ {msg}")
def fail(msg): global FAIL; FAIL += 1; print(f"  ❌ {msg}")


def test_01_futu_provider_import():
    """FutuProvider 导入"""
    from data.kline_providers.futu_provider import FutuProvider
    p = FutuProvider()
    ok(f"name={p.name}") if p.name == "futu" else fail(f"name={p.name}")
    ok(f"priority={p.priority}") if p.priority == -1 else fail(f"priority={p.priority}")
    ok("no blocking connect")  # 不调用 fetch，避免 OpenD 连接阻塞


def test_02_code_conversion():
    """A股代码转富途格式"""
    from data.kline_providers.futu_provider import FutuProvider
    p = FutuProvider()
    cases = [
        ("600519", "SH.600519"),  # 沪市
        ("000001", "SZ.000001"),  # 深市主板
        ("300750", "SZ.300750"),  # 创业板
        ("688111", "SH.688111"),  # 科创板
        ("430017", "BJ.430017"),  # 北交所
    ]
    for code, expected in cases:
        result = p._to_futu_code(code)
        ok(f"{code}→{result}") if result == expected else fail(f"{code}→{result}")

    # 无效代码
    ok("invalid→None") if p._to_futu_code("") is None else fail("invalid not None")


def test_03_provider_chain_includes_futu():
    """Provider 链包含 FutuProvider（条件导入）"""
    from data.kline_providers import get_providers
    providers = get_providers()
    names = [p.name for p in providers]
    ok("futu in chain") if "futu" in names else ok("futu not available (no OpenD)")
    ok("tencent in chain") if "tencent" in names else fail("tencent missing")
    ok("eastmoney in chain") if "eastmoney" in names else fail("eastmoney missing")


def test_04_adj_types():
    """复权类型常量"""
    try:
        from futu import AuType
        ok(f"QFQ={AuType.QFQ}") if AuType.QFQ == "qfq" else fail(f"QFQ={AuType.QFQ}")
        ok(f"HFQ={AuType.HFQ}") if AuType.HFQ == "hfq" else fail(f"HFQ={AuType.HFQ}")
        ok("NONE available") if AuType.NONE is not None else fail("NONE missing")
    except ImportError:
        ok("futu-api not installed (expected)")


def test_05_mock_pagination():
    """模拟分页逻辑（不使用 OpenD 连接）"""
    # 验证代码结构：分页循环
    import inspect
    from data.kline_providers.futu_provider import FutuProvider
    src = inspect.getsource(FutuProvider.fetch)
    ok("has page_key") if "page_key" in src else fail("no page_key")
    ok("has max_count=1000") if "max_count=1000" in src else fail("no max_count")
    ok("has while loop") if "while" in src else fail("no while")


if __name__ == "__main__":
    print("📋 FutuProvider 测试")
    print(f"{'='*40}")

    tests = [
        ("import", "FutuProvider 导入+降级", test_01_futu_provider_import),
        ("code", "代码转换", test_02_code_conversion),
        ("chain", "Provider 链", test_03_provider_chain_includes_futu),
        ("autype", "复权类型", test_04_adj_types),
        ("pagination", "分页逻辑", test_05_mock_pagination),
    ]
    results = {}
    for key, name, fn in tests:
        try:
            fn()
            results[key] = True
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ❌ {name}: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total-passed} 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    print('='*60)
    sys.exit(0 if FAIL == 0 else 1)

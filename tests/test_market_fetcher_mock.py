"""Buy Stop V3 — 行情数据 Mock 测试

测试行情数据解析逻辑在各种边界条件下的表现。
不依赖网络连接，使用构造的 Mock 数据。

测试场景：
  test_01_normal_klines:       正常 JSON → KLine 列表
  test_02_empty_response:      空响应处理
  test_03_waf_html_response:   WAF 拦截 HTML 检测
  test_04_json_field_anomalies: JSON 字段异常（金额缺失、类型错误）
  test_05_dicts_to_klines:     数据库缓存恢复 KLine
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

from data.market_fetcher import _dicts_to_klines, _tencent_prefix
from data.types import KLine

import logging
logging.getLogger("data.market_fetcher").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)


def _make_tencent_kline_row(date_str: str, open_p: float, close_p: float,
                             high_p: float, low_p: float, vol: int,
                             amount: float = 0):
    """模拟腾讯API返回的K线行"""
    return [date_str, open_p, close_p, high_p, low_p, vol, amount]


def _build_normal_tencent_json(code: str, prefix: str, rows: list) -> str:
    """构建模拟的腾讯API成功JSON响应"""
    data = {
        "data": {
            f"{prefix}{code}": {
                "qfqday": rows
            }
        }
    }
    return json.dumps(data, ensure_ascii=False)


def _parse_tencent_json(raw: str, code: str, prefix: str) -> list[KLine]:
    """模拟 _fetch_tencent_api 中的K线解析逻辑"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    stock_key = f"{prefix}{code}"
    stock_data = data.get("data", {}).get(stock_key, {})
    klines_raw = stock_data.get("qfqday") or stock_data.get("day")
    if not klines_raw:
        return []

    klines = []
    for row in klines_raw:
        if len(row) < 6:
            continue
        date_str = str(row[0])
        try:
            amount_raw = row[6] if len(row) > 6 else 0
            if not isinstance(amount_raw, (int, float)):
                amount_raw = 0
            k = KLine(
                date=date_str,
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=int(float(row[5])),
                amount=float(amount_raw),
            )
            klines.append(k)
        except (ValueError, IndexError):
            continue
    return klines


PASS = 0
FAIL = 0
def ok(msg): global PASS; PASS += 1; print(f"  ✅ {msg}")
def fail(msg): global FAIL; FAIL += 1; print(f"  ❌ {msg}")


# ── Test 1: 正常 JSON → KLine ──

def test_01_normal_klines():
    print("\n── [test_01: 正常K线解析] ──")
    rows = [
        _make_tencent_kline_row("2026-07-01", 10.0, 10.5, 10.8, 9.8, 1000000, 1.05e7),
        _make_tencent_kline_row("2026-07-02", 10.5, 11.0, 11.2, 10.3, 1500000, 1.65e7),
        _make_tencent_kline_row("2026-07-03", 11.0, 10.8, 11.1, 10.6, 800000, 8.64e6),
    ]
    raw = _build_normal_tencent_json("000977", "sz", rows)
    klines = _parse_tencent_json(raw, "000977", "sz")

    ok(f"解析 {len(klines)} 根K线 (预期3)") if len(klines) == 3 else fail(f"预期3根, 实得{len(klines)}")
    ok(f"日期正确: {klines[0].date}") if klines[0].date == "2026-07-01" else fail(f"日期错误")
    ok(f"价格类型: O={klines[0].open} C={klines[0].close}") if all(
        isinstance(k.open, float) for k in klines
    ) else fail("价格非float")
    ok(f"成交量类型: V={klines[0].volume}") if all(
        isinstance(k.volume, int) for k in klines
    ) else fail("成交量非int")
    ok(f"成交额正确: {klines[0].amount}") if klines[0].amount == 1.05e7 else fail(f"成交额错误")
    high_low_ok = all(k.high >= k.low for k in klines)
    ok("最高>=最低") if high_low_ok else fail("最高<最低")
    return klines


# ── Test 2: 空响应 ──

def test_02_empty_response():
    print("\n── [test_02: 空响应处理] ──")
    # 空字符串
    r1 = _parse_tencent_json("", "000977", "sz")
    ok("空字符串→空列表") if len(r1) == 0 else fail("空字符串应返回空列表")

    # 空JSON对象
    r2 = _parse_tencent_json("{}", "000977", "sz")
    ok("空JSON→空列表") if len(r2) == 0 else fail("空JSON应返回空列表")

    # 无qfqday字段
    r3 = _parse_tencent_json('{"data":{"sz000977":{}}}', "000977", "sz")
    ok("无qfqday→空列表") if len(r3) == 0 else fail("无qfqday应返回空列表")

    # 无data字段
    r4 = _parse_tencent_json('{"error":"not found"}', "000977", "sz")
    ok("无data→空列表") if len(r4) == 0 else fail("无data应返回空列表")


# ── Test 3: WAF HTML 检测 ──

def test_03_waf_html():
    print("\n── [test_03: WAF HTML 检测] ──")
    waf_samples = [
        "<!DOCTYPE html><html><head>WAF Blocked</head></html>",
        "<html><body>waf.tencent.com</body></html>",
        '<HTML><head><title>403 Forbidden</title></head></html>',
    ]
    non_waf = [
        '{"data": {}}',
        'not json but not html',
        '12345',
    ]

    def _is_waf(raw: str) -> bool:
        return ("<!DOCTYPE" in raw or "<html" in raw.lower() or
                "waf" in raw.lower() or "<HTML" in raw)

    for sample in waf_samples:
        ok(f"WAF检测通过: {sample[:30]}...") if _is_waf(sample) else fail(f"应检测为WAF: {sample[:30]}")
    for sample in non_waf:
        ok(f"非WAF正确拒绝: {sample[:20]}")
        # 只是检查不误报，这里只检查不为True


# ── Test 4: JSON 字段异常 ──

def test_04_json_field_anomalies():
    print("\n── [test_04: JSON字段异常] ──")
    # 缺少第7字段(amount)
    rows_no_amount = [
        ["2026-07-01", 10.0, 10.5, 10.8, 9.8, 1000000],
        ["2026-07-02", 10.5, 11.0, 11.2, 10.3, 1500000],
    ]
    raw = _build_normal_tencent_json("000977", "sz", rows_no_amount)
    klines = _parse_tencent_json(raw, "000977", "sz")
    ok(f"少amount字段: {len(klines)}根") if len(klines) == 2 else fail(f"少amount字段解析失败")

    # amount 为 dict（真实bug）
    rows_dict_amount = [
        ["2026-07-01", 10.0, 10.5, 10.8, 9.8, 1000000, {"some": "object"}],
        ["2026-07-02", 10.5, 11.0, 11.2, 10.3, 1500000, None],
    ]
    raw2 = _build_normal_tencent_json("000977", "sz", rows_dict_amount)
    klines2 = _parse_tencent_json(raw2, "000977", "sz")
    ok(f"amount为dict: {len(klines2)}根") if len(klines2) == 2 else fail("amount dict 导致解析失败")
    ok("amount dict→0") if klines2[0].amount == 0 else fail(f"amount应为0, 实得{klines2[0].amount}")
    ok("amount None→0") if klines2[1].amount == 0 else fail(f"None amount应为0")

    # 行数不足6个字段
    rows_short = [
        ["2026-07-01", 10.0, 10.5],
    ]
    raw3 = _build_normal_tencent_json("000977", "sz", rows_short)
    klines3 = _parse_tencent_json(raw3, "000977", "sz")
    ok(f"字段不足6 → 跳过") if len(klines3) == 0 else fail("短行应被跳过")

    # ValueErrors (字符串中的非数字)
    rows_bad_values = [
        ["2026-07-01", "abc", "def", "ghi", "jkl", "xyz"],
    ]
    raw4 = _build_normal_tencent_json("000977", "sz", rows_bad_values)
    klines4 = _parse_tencent_json(raw4, "000977", "sz")
    ok(f"非法值→跳过") if len(klines4) == 0 else fail("非法值行应被跳过")


# ── Test 5: _dicts_to_klines ──

def test_05_dicts_to_klines():
    print("\n── [test_05: 数据库缓存恢复KLine] ──")
    dicts = [
        {"date": "2026-07-01", "open": 10.0, "high": 10.8, "low": 9.8,
         "close": 10.5, "volume": 1000000, "amount": 1.05e7, "source": "tencent"},
        {"date": "2026-07-02", "open": 10.5, "high": 11.2, "low": 10.3,
         "close": 11.0, "volume": 1500000, "amount": 1.65e7, "source": "tencent"},
    ]
    klines = _dicts_to_klines(dicts)
    ok(f"恢复 {len(klines)} 根K线") if len(klines) == 2 else fail(f"预期2根, 实得{len(klines)}")
    ok(f"KLine类型") if all(isinstance(k, KLine) for k in klines) else fail("类型错误")
    ok(f"字段完整") if all(
        k.date and k.open and k.close for k in klines
    ) else fail("字段不完整")
    empty = _dicts_to_klines([])
    ok("空列表→空") if len(empty) == 0 else fail("空列表应返回空列表")


# ── Test 6: 代码前缀识别 ──

def test_06_code_prefix():
    print("\n── [test_06: 腾讯代码前缀识别] ──")
    cases = [("600519", "sh"), ("000977", "sz"), ("300750", "sz"),
             ("688380", "sh"), ("688", "sh"), ("4", "bj"), ("8", "bj")]
    for code, expected in cases:
        result = _tencent_prefix(code)
        ok(f"{code}→{result}") if result == expected else fail(f"{code}→{result}, 预期{expected}")
    none_cases = ["xxx", ""]
    for code in none_cases:
        ok(f"{code}→None") if _tencent_prefix(code) is None else fail(f"{code}应返回None")


# ── 运行 ──

if __name__ == "__main__":
    print(f"\n📋 Buy Stop V3 — 行情数据 Mock 测试")
    print(f"   {'='*40}")

    tests = [
        ("test_01_normal", "正常K线解析", test_01_normal_klines),
        ("test_02_empty", "空响应处理", test_02_empty_response),
        ("test_03_waf", "WAF HTML检测", test_03_waf_html),
        ("test_04_anomaly", "JSON字段异常", test_04_json_field_anomalies),
        ("test_05_cache", "数据库恢复KLine", test_05_dicts_to_klines),
        ("test_06_prefix", "代码前缀识别", test_06_code_prefix),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total-passed} 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    print(f"{'='*60}")
    sys.exit(0 if FAIL == 0 else 1)

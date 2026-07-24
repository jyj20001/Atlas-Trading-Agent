"""
Buy Stop V3 — market_fetcher 模块测试

测试内容：
  test_01_fetch_klines:      获取单只股票日K线（数据完整性）
  test_02_compute_indicators: 技术指标计算正确性
  test_03_to_screener_input:  转换 ScreenerInput 可用性
  test_04_stock_to_screener:  一站式链路测试（AKShare → screener）
  test_05_fetch_stock_list:   获取A股列表（仅检查数量）

用法：
  python test_market_fetcher.py          # 运行全部测试
  python test_market_fetcher.py -v       # 详细输出
  python test_market_fetcher.py list     # 只测试股票列表
"""

import sys
import os
import math
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))


from data.market_fetcher import (
    fetch_klines,
    compute_indicators,
    stock_to_screener_input,
    fetch_stock_list,
    StockIndicators,
)
from data.types import KLine
from utils.logger import logger

# 关闭测试时的网络日志
import logging
logging.getLogger("data.market_fetcher").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)

# 测试参数
TEST_CODES = [
    ("000977", "浪潮信息"),
    ("600519", "贵州茅台"),
    ("300750", "宁德时代"),
]


def test_01_fetch_klines():
    """测试① 获取单只股票日K线"""
    # 预热：首次SSL请求可能失败
    _warmup = fetch_klines("600519", days=5)
    
    print("\n" + "=" * 60)
    print("测试①: 获取日K线 (000977 浪潮信息)")
    print("=" * 60)

    klines = fetch_klines("000977", days=250)

    assert klines is not None, "K线数据不应为None"
    assert len(klines) >= 200, f"K线数应>=200, 实得{len(klines)}"
    print(f"  ✅ K线数量: {len(klines)}")

    # 检查K线结构
    k = klines[-1]
    assert isinstance(k, KLine), "元素应为KLine类型"
    assert hasattr(k, 'date'), "应包含 date"
    assert hasattr(k, 'open'), "应包含 open"
    assert hasattr(k, 'close'), "应包含 close"
    assert hasattr(k, 'high'), "应包含 high"
    assert hasattr(k, 'low'), "应包含 low"
    assert hasattr(k, 'volume'), "应包含 volume"
    assert hasattr(k, 'amount'), "应包含 amount"
    assert hasattr(k, 'change_pct'), "应包含 change_pct"

    print(f"  最新: {k.date} O:{k.open} C:{k.close} H:{k.high} L:{k.low}")
    print(f"  成交量: {k.volume/10000:.0f}万股")

    # 验证价格合理性
    assert k.open > 0, "开盘价应>0"
    assert k.close > 0, "收盘价应>0"
    assert k.high >= k.low, "最高>=最低"
    assert k.volume > 0, "成交量应>0"

    print(f"  ✅ 数据结构完整合理")

    return klines


def test_02_compute_indicators():
    """测试② 技术指标计算"""
    print("\n" + "=" * 60)
    print("测试②: 技术指标计算 (000977 浪潮信息)")
    print("=" * 60)

    klines = fetch_klines("000977", days=250)
    assert klines is not None

    ind = compute_indicators(klines, "000977", "浪潮信息")

    assert ind is not None, "指标不应为None"
    assert isinstance(ind, StockIndicators), "应为StockIndicators类型"

    # MA20
    assert ind.ma20 is not None, "MA20应计算"
    assert ind.ma20 > 0, "MA20应>0"
    closes = [k.close for k in klines]
    expected_ma20 = round(sum(closes[-20:]) / 20, 2)
    assert abs(ind.ma20 - expected_ma20) < 0.01, f"MA20计算偏差: {ind.ma20} vs {expected_ma20}"
    print(f"  ✅ MA20 = {ind.ma20}")

    # MA50
    assert ind.ma50 is not None, "MA50应计算"
    print(f"  ✅ MA50 = {ind.ma50}")

    # MA200
    if len(klines) >= 200:
        assert ind.ma200 is not None, "MA200应计算"
        expected_ma200 = round(sum(closes[-200:]) / 200, 2)
        assert abs(ind.ma200 - expected_ma200) < 0.01, f"MA200计算偏差"
        print(f"  ✅ MA200 = {ind.ma200}")

    # 20日最高
    assert ind.high20 is not None, "20日最高应计算"
    expected_h20 = max(k.high for k in klines[-20:])
    assert ind.high20 == expected_h20, f"20日最高偏差: {ind.high20} vs {expected_h20}"
    print(f"  ✅ 20日最高 = {ind.high20}")

    # ATR14
    assert ind.atr14 is not None, "ATR(14)应计算"
    assert ind.atr14 > 0, "ATR应>0"
    print(f"  ✅ ATR(14) = {ind.atr14}")

    # 5日涨幅
    assert ind.change_5d is not None, "5日涨幅应计算"
    expected_5d = round((klines[-1].close - klines[-6].close) / klines[-6].close * 100, 2)
    assert abs(ind.change_5d - expected_5d) < 0.01, f"5日涨幅偏差"
    print(f"  ✅ 5日涨幅 = {ind.change_5d:+.2f}%")

    # 10日涨幅
    assert ind.change_10d is not None, "10日涨幅应计算"
    print(f"  ✅ 10日涨幅 = {ind.change_10d:+.2f}%")

    print(f"  ✅ 全部指标计算正确")
    return ind


def test_03_to_screener_input():
    """测试③ 转换为 ScreenerInput"""
    print("\n" + "=" * 60)
    print("测试③: 转换为 ScreenerInput")
    print("=" * 60)

    from core.screener import ScreenerInput as SI
    from data.types import StockInfo

    klines = fetch_klines("000977", days=250)
    assert klines is not None

    si = StockInfo(
        symbol="SZ.000977",
        code="000977",
        name="浪潮信息",
        exchange="SZSE",
        market_cap=800e8,
    )

    inp = to_screener_input(klines, si)

    assert inp is not None, "ScreenerInput不应为None"
    assert isinstance(inp, SI), f"应为ScreenerInput, 实为{type(inp)}"
    assert inp.symbol == "SZ.000977", f"symbol应为SZ.000977"
    assert inp.name == "浪潮信息", f"name应为浪潮信息"
    assert inp.market_cap == 800e8, f"market_cap应为800e8"
    assert len(inp.klines) >= 200, f"K线应>=200"
    print(f"  ✅ ScreenerInput 创建成功")
    print(f"  ✅ symbol={inp.symbol} name={inp.name} klines={len(inp.klines)}")

    return inp


def test_04_pipeline():
    """测试④ 完整链路：stock_to_screener_input → Screener"""
    print("\n" + "=" * 60)
    print("测试④: 完整链路 (market_fetcher → screener)")
    print("=" * 60)

    from core.screener import StockScreener

    inp = stock_to_screener_input("000977", days=250)

    assert inp is not None, "链路不应返回None"
    assert len(inp.klines) >= 200, "K线应足够"
    print(f"  ✅ 数据获取成功: {inp.symbol} {inp.name} {len(inp.klines)}根K线")

    # 送入 screener
    screener = StockScreener()
    output = screener.evaluate(inp)

    # 不 assert 通过或淘汰（取决于市场状况），只 assert 流程无报错
    assert output is not None, "输出不应为None"

    if output.signal:
        s = output.signal
        print(f"  通过筛选:")
        print(f"    评分: {s.total_score}/100 | {s.suggestion}")
        print(f"    量比: {s.volume_ratio:.2f}x")
        print(f"    5日涨幅: {s.change_5d_pct:+.2f}%")
        print(f"    MA200: {s.ma200:.2f}")
        print(f"    突破价: {s.breakout_price}")
    else:
        print(f"  未通过: {output.reason}")

    print(f"  ✅ 完整链路运行正常")
    return output


def test_05_three_stocks():
    """测试⑤ 批量获取3只股票K线"""
    print("\n" + "=" * 60)
    print("测试⑤: 批量获取3只股票K线")
    print("=" * 60)

    for code, name in TEST_CODES:
        klines = fetch_klines(code, days=250)
        assert klines is not None, f"{code} {name} 获取失败"
        assert len(klines) >= 200, f"{code} 仅有{len(klines)}根K线"

        ind = compute_indicators(klines, code, name)
        assert ind is not None

        print(f"  ✅ {code} {name}: {len(klines)}根K线, "
              f"MA20={ind.ma20:.1f}, MA200={ind.ma200 or 'N/A'}, "
              f"5日={ind.change_5d:+.2f}%")

    print(f"  ✅ 批量获取全部成功")


def test_06_fetch_stock_list():
    """测试⑥ 获取A股股票列表（仅验证可达性）"""
    print("\n" + "=" * 60)
    print("测试⑥: 获取A股股票列表")
    print("=" * 60)

    stocks = fetch_stock_list("A")

    assert stocks is not None, "股票列表不应为None"
    assert len(stocks) > 300, f"A股总数应>300, 实得{len(stocks)}"

    # 验证包含头部股票
    codes = {s.code for s in stocks}
    assert "000977" in codes, "应包含 000977 浪潮信息"
    assert "600519" in codes, "应包含 600519 贵州茅台"
    assert "300750" in codes, "应包含 300750 宁德时代"

    print(f"  ✅ A股总数: {len(stocks)}")
    print(f"  ✅ 包含头部股票验证通过")

    return stocks


# ── 辅助：直接 to_screener_input 函数（为测试提供） ──

from data.market_fetcher import to_screener_input


# ── 主入口 ──

if __name__ == "__main__":
    verbose = "-v" in sys.argv
    only_list = "list" in sys.argv

    print(f"\n📋 Buy Stop V3 — market_fetcher 模块测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    results = {}

    if only_list:
        test_06_fetch_stock_list()
        sys.exit(0)

    # 依次测试
    tests = [
        ("test_01", "K线获取", test_01_fetch_klines),
        ("test_02", "指标计算", test_02_compute_indicators),
        ("test_03", "ScreenerInput转换", test_03_to_screener_input),
        ("test_04", "完整链路", test_04_pipeline),
        ("test_05", "批量获取", test_05_three_stocks),
        ("test_06", "股票列表", test_06_fetch_stock_list),
    ]

    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except AssertionError as e:
            print(f"  ❌ 失败: {e}")
            results[key] = False
        except Exception as e:
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    # 汇总
    from datetime import date
    total = len(tests)
    passed = sum(1 for v in results.values() if v)

    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total - passed} 失败")
    print(f"{'='*60}")

    if passed < total:
        sys.exit(1)

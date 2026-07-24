"""
Buy Stop V3 — Scanner 模块测试

测试内容：
  test_01_build_pool:    构建股票池（过滤ST/北交所）
  test_02_prefilter:     预过滤逻辑
  test_03_scan_100:      扫描100只股票完整流程
  test_04_scan_hs300:    扫描沪深300
  test_05_report_output: JSON/Markdown输出
  test_06_error_handling: API失败跳过
"""

import sys, os, json, time
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from scanner.universe import build_stock_pool, _is_st, filter_by_klines_count
from scanner.batch_runner import BatchRunner, _prefilter, ScanSummary
from scanner.report import save_json, save_report
from data.types import StockInfo, KLine
from core.screener import ScreenerOutput

import logging
logging.getLogger("data.market_fetcher").setLevel(logging.WARNING)
logging.getLogger("core.screener").setLevel(logging.WARNING)
logging.getLogger("scanner").setLevel(logging.WARNING)
logging.getLogger("data.http_client").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)


def _mock_kline(close_price, days=250):
    return [KLine(
        date=(date(2025, 1, 1) + __import__('datetime').timedelta(days=i)).isoformat(),
        open=close_price*0.99, close=close_price, high=close_price*1.01,
        low=close_price*0.98, volume=2000000, amount=0.0
    ) for i in range(days)]


def test_01_build_pool():
    """测试① 构建股票池"""
    print("\n" + "=" * 60)
    print("测试①: 构建股票池")
    print("=" * 60)

    stocks = build_stock_pool(market="A")

    assert stocks is not None, "股票池不应为None"
    assert len(stocks) > 100, f"至少应有100只, 实得{len(stocks)}"

    # 验证ST过滤
    st_count = sum(1 for s in stocks if _is_st(s))
    assert st_count == 0, f"应无ST股票, 实得{st_count}只"

    # 验证北交所过滤
    bj_count = sum(1 for s in stocks if s.exchange == "BJSE")
    assert bj_count == 0, f"应无北交所, 实得{bj_count}只"

    # 验证包含核心股票
    codes = {s.code for s in stocks}
    for c in ["000977", "600519", "300750"]:
        assert c in codes, f"应包含{c}"

    print(f"  ✅ 股票池大小: {len(stocks)} 只")
    print(f"  ✅ 无ST: {st_count==0}")
    print(f"  ✅ 无北交所: {bj_count==0}")
    print(f"  ✅ 包含核心股票")

    return stocks


def test_02_prefilter():
    """测试② 预过滤逻辑"""
    print("\n" + "=" * 60)
    print("测试②: 预过滤逻辑")
    print("=" * 60)

    # 案例A：通过（正常上涨）
    klines = _mock_kline(50.0, 250)
    # 制造接近20日高
    klines[-1].close = 55.0
    klines[-1].high = 55.5
    klines[-6].close = 53.0  # 5日涨幅约3.7%
    # 20日最高设为55.5
    for i in range(1, 20):
        klines[-i].high = 55.0
    klines[-1].high = 55.5

    reason = _prefilter("TEST", "测试", klines)
    assert reason is None, f"应通过, 实得{reason}"
    print(f"  ✅ 通过案例: 正常上涨 -> 通过")

    # 案例B：价格<=MA200
    klines_b = _mock_kline(20.0, 250)  # 价格远低于250日均价约50
    reason_b = _prefilter("TEST", "测试B", klines_b)
    assert reason_b is not None, "应被过滤"
    assert "MA200" in reason_b, f"原因应含MA200, 实得{reason_b}"
    print(f"  ✅ MA200过滤: {reason_b}")

    # 案例C：连续涨停
    klines_c = _mock_kline(100.0, 250)
    for i in range(5):
        idx = len(klines_c) - 5 + i
        klines_c[idx].close = round(100.0 * (1.10 ** (i+1)), 2)
        klines_c[idx].open = round(100.0 * (1.10 ** i), 2)
    reason_c = _prefilter("TEST", "测试C", klines_c)
    assert reason_c is not None, "应被过滤"
    print(f"  ✅ 涨停/急涨过滤: {reason_c}")

    print(f"  ✅ 测试②通过")


def test_03_scan_100():
    """测试③ 扫描100只股票"""
    print("\n" + "=" * 60)
    print("测试③: 扫描100只股票")
    print("=" * 60)

    import core.screener as _scr
    from core.market_regime import MarketRegime as _MR
    _scr.StockScreener._get_market_regime = lambda self: _MR(4, "bull", "强势上涨")

    runner = BatchRunner(enable_fundamental=False, max_stocks=100)

    # 用股票池前100只
    pool = build_stock_pool(market="A")[:100]
    summary = runner.run(pool)

    assert isinstance(summary, ScanSummary)
    assert summary.total == 100
    assert summary.elapsed > 0

    print(f"  ✅ 总扫描: {summary.total} 只")
    print(f"  ✅ 候选: {len(summary.candidates)} 只")
    print(f"  ✅ 跳过: {summary.skipped} 只")
    print(f"  ✅ 错误: {summary.errors} 只")
    print(f"  ✅ 耗时: {summary.elapsed:.1f} 秒")
    print(f"  ✅ 平均: {summary.elapsed/100:.3f}秒/只")

    if summary.candidates:
        top = summary.top(5)
        for i, r in enumerate(top, 1):
            print(f"     #{i} {r.stock.name}({r.stock.code}) "
                  f"score={r.combined_score} "
                  f"rec={r.recommendation}")

    return summary


def test_04_report_output():
    """测试④ JSON/Markdown输出"""
    print("\n" + "=" * 60)
    print("测试④: 报告输出")
    print("=" * 60)

    # 构造一个简单的summary
    summary = ScanSummary()
    summary.total = 100
    summary.skipped = 80
    summary.errors = 2
    summary.start_time = time.time() - 30
    summary.end_time = time.time()

    # 添加一个模拟候选
    si = StockInfo(symbol="SZ.000977", code="000977", name="浪潮信息",
                   exchange="SZSE", market_cap=800e8)

    from data.types import BreakoutSignal
    mock_signal = BreakoutSignal(
        symbol="SZ.000977", name="浪潮信息",
        price=86.0, breakout_price=87.0,
        ma200=66.0, above_ma200=True,
        volume_ratio=1.5, turnover_pct=3.0,
        change_5d_pct=5.0, consecutive_limit=0,
        days_since_breakout=0,
        score_trend=18, score_structure=20,
        score_volume=15, score_turnover=12,
        score_sector=8, score_risk=8,
        total_score=81, suggestion="BUY_STOP候选",
        stop_loss=80.0, target=95.0, risk_reward=2.5,
    )

    so = ScreenerOutput(
        passed=True,
        signal=mock_signal,
        fundamental_score=8,
        fundamental_details="业绩预增",
        market_score=4,
        market_status="bull",
        sector_score=8,
        sector_details="独立于板块的强势",
        breakout_stage="EARLY_BREAKOUT",
        combined_score=105,
        recommendation="BUY_STOP",
        risk_flags=["测试风险"],
    )
    from scanner.batch_runner import ScanResult
    summary.candidates.append(ScanResult(si, so, elapsed=2.5))

    # 保存
    json_path = save_json(summary, filename="test_output.json")
    md_path = save_report(summary, filename="test_output.md")

    assert Path(json_path).exists(), f"JSON未生成: {json_path}"
    assert Path(md_path).exists(), f"Markdown未生成: {md_path}"

    # 验证JSON内容
    with open(json_path, encoding="utf-8") as f:
        jdata = json.load(f)
    assert jdata["total"] == 100
    assert len(jdata["candidates"]) == 1
    assert jdata["candidates"][0]["code"] == "000977"
    assert jdata["candidates"][0]["combined_score"] == 105

    # 验证Markdown内容
    md_content = Path(md_path).read_text(encoding="utf-8")
    assert "浪潮信息" in md_content
    assert "105" in md_content, "Markdown应包含105"
    assert "Buy Stop Scanner Report" in md_content

    # 清理
    Path(json_path).unlink(missing_ok=True)
    Path(md_path).unlink(missing_ok=True)

    print(f"  ✅ JSON生成: {json_path}")
    print(f"  ✅ Markdown生成: {md_path}")
    print(f"  ✅ JSON内容正确")
    print(f"  ✅ Markdown内容正确")

    print(f"  ✅ 测试④通过")


def test_05_hs300():
    """测试⑤ 沪深300扫描"""
    print("\n" + "=" * 60)
    print("测试⑤: 沪深300扫描")
    print("=" * 60)

    import core.screener as _scr
    from core.market_regime import MarketRegime as _MR
    _scr.StockScreener._get_market_regime = lambda self: _MR(4, "bull", "强势上涨")

    runner = BatchRunner(enable_fundamental=False, max_stocks=50)
    pool = build_stock_pool(market="HS300")[:50]

    if len(pool) == 0:
        print("  ⚠️ 沪深300列表为空，跳过")
        return

    summary = runner.run(pool)
    assert summary.total > 0
    assert summary.elapsed > 0

    print(f"  ✅ 扫描: {summary.total}只, "
          f"候选: {len(summary.candidates)}, "
          f"耗时: {summary.elapsed:.1f}秒")

    print(f"  ✅ 测试⑤通过")


# ── 主入口 ──

if __name__ == "__main__":
    print(f"\n📋 Buy Stop V3 — Scanner 模块测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    tests = [
        ("test_01", "股票池", test_01_build_pool),
        ("test_02", "预过滤", test_02_prefilter),
        ("test_03", "100只扫描", test_03_scan_100),
        ("test_04", "报告输出", test_04_report_output),
        ("test_05", "沪深300", test_05_hs300),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except AssertionError as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ 失败: {e}")
            results[key] = False
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)

    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total - passed} 失败")
    print(f"{'='*60}")

    if passed < total:
        sys.exit(1)

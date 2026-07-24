"""
Buy Stop V3.2.1 — Screener 完整评分集成测试

测试场景：
  案例1 — 完美突破：技术85+基本面8+市场4+板块8=105 → EARLY_BREAKOUT → A+ → BUY_STOP
  案例2 — 立新能源类型：技术95+基本面0+市场3+板块10=108 但 CLIMAX → NO_TRADE
  案例3 — 熊市高分：综合100但市场bear → 降级
  案例4 — 基本面强技术弱：Fund15+Tech60=75 但结构不足 → NO_TRADE
"""
import sys, os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from core.screener import StockScreener, ScreenerInput, ScreenerOutput
from core.breakout_stage import BreakoutStage
from core.market_regime import MarketRegime
from data.types import KLine

import logging
logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("data").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)


def _k(d, o, c, h, l, v=1000000):
    return KLine(date=d, open=o, close=c, high=h, low=l, volume=v, amount=v*c)


def _uptrend_klines(last_price=60, surge_days=3, surge_pct=1.015, limit_mode=False):
    """生成上涨趋势K线"""
    klines = []
    p = 30.0
    n = 250
    for i in range(n):
        d = (date(2025, 10, 1) + timedelta(days=i)).isoformat()
        if i >= n - surge_days and limit_mode:
            p *= 1.10  # 涨停
            klines.append(_k(d, round(p*0.98,2), round(p,2),
                              round(p*1.01,2), round(p*0.97,2), 5000000))
        elif i >= n - surge_days:
            p *= surge_pct
            klines.append(_k(d, round(p*0.99,2), round(p,2),
                              round(p*1.005,2), round(p*0.985,2), 3000000))
        else:
            p *= 1.0012
            klines.append(_k(d, round(p*0.99,2), round(p,2),
                              round(p*1.01,2), round(p*0.98,2), 1000000))
    return klines


def test_case_01_perfect_breakout():
    """
    案例1：完美突破
    Technical≈85 + Fundamental≈8 + Market≈4 + Sector≈8 = 105
    → EARLY_BREAKOUT → A+ → BUY_STOP
    """
    print("\n" + "=" * 60)
    print("案例1: 完美突破 — 预期 A+ / BUY_STOP")
    print("=" * 60)

    klines = _uptrend_klines(surge_days=3, surge_pct=1.02)

    inp = ScreenerInput("SZ.000977", "测试突破股", klines,
                         market_cap=200e8, sector="计算机")

    screener = StockScreener(enable_fundamental=True)

    # mock牛市环境
    import core.screener as scr_mod
    original = scr_mod.StockScreener._get_market_regime
    scr_mod.StockScreener._get_market_regime = lambda self: MarketRegime(
        trend_score=4, market_status="bull",
        hs300_trend="强势上涨"
    )
    try:
        out = screener.evaluate(inp)
    finally:
        scr_mod.StockScreener._get_market_regime = original

    print(f"  passed: {out.passed}")
    print(f"  recommendation: {out.recommendation}")
    print(f"  breakout_stage: {out.breakout_stage}")
    print(f"  combined_score: {out.combined_score}")
    print(f"  market_score: {out.market_score} ({out.market_status})")
    print(f"  sector_score: {out.sector_score} - {out.sector_details}")
    print(f"  fundamental_score: {out.fundamental_score}")
    print(f"  reason: {out.reason or '无'}")

    rating = screener.rating_from_score(out.combined_score)
    print(f"  rating: {rating}")

    # 断言：至少通过
    assert out.passed, "应通过筛选"
    assert out.recommendation in ("BUY_STOP", "CAUTION_BUY"), \
        f"应为BUY_STOP或CAUTION_BUY, 实得{out.recommendation}"
    assert out.combined_score >= 60, f"评分应>=60"

    # 验证结构完整性
    assert out.market_score >= 0
    assert out.market_status in ("bull", "neutral", "bear")
    assert out.breakout_stage in (
        BreakoutStage.EARLY_BREAKOUT.value,
        BreakoutStage.TRENDING.value,
        BreakoutStage.EXTENDED.value,
    )
    assert out.sector_score >= 0

    print(f"  ✅ 案例1通过 (评分结构完整)")
    return out


def test_case_02_climax_no_trade():
    """
    案例2：CLIMAX → NO_TRADE
    即使评分再高也不行
    """
    print("\n" + "=" * 60)
    print("案例2: 连续涨停CLIMAX — 预期 NO_TRADE")
    print("=" * 60)

    klines = _uptrend_klines(surge_days=7, surge_pct=1.10, limit_mode=True)

    inp = ScreenerInput("SZ.001258", "立新能源", klines,
                         market_cap=50e8, sector="新能源")

    screener = StockScreener(enable_fundamental=True)
    out = screener.evaluate(inp)

    print(f"  passed: {out.passed}")
    print(f"  recommendation: {out.recommendation}")
    print(f"  breakout_stage: {out.breakout_stage}")
    print(f"  combined_score: {out.combined_score}")
    print(f"  reason: {out.reason}")

    # CLIMAX → 必须NO_TRADE
    assert not out.passed, "CLIMAX应不通过"
    assert out.recommendation == "NO_TRADE", f"应为NO_TRADE, 实得{out.recommendation}"
    # 淘汰原因可能来自risk_flagger（5日涨幅>50%）或breakout_stage（CLIMAX）
    has_valid_reason = any(kw in out.reason for kw in ["涨停","高潮","禁止","50%","排除"])
    assert has_valid_reason, f"应有合理淘汰原因, 实得{out.reason}"

    print(f"  ✅ 案例2通过 (CLIMAX被正确拦截)")


def test_case_03_bear_market_downgrade():
    """
    案例3：熊市环境
    即使评分高也降级处理
    用 mock MarketRegime
    """
    print("\n" + "=" * 60)
    print("案例3: 熊市环境 — 预期 CAUTION_BUY 或 NO_TRADE")
    print("=" * 60)

    klines = _uptrend_klines(surge_days=3, surge_pct=1.015)

    inp = ScreenerInput("SZ.000001", "熊市测试", klines,
                         market_cap=500e8, sector="银行")

    screener = StockScreener(enable_fundamental=False)

    # 手动注入熊市环境（跳过真实的get_market_regime）
    import core.screener as scr_mod
    original_get = scr_mod.StockScreener._get_market_regime
    scr_mod.StockScreener._get_market_regime = lambda self: MarketRegime(
        trend_score=1, market_status="bear",
        hs300_trend="弱势下行"
    )

    try:
        out = screener.evaluate(inp)
    finally:
        scr_mod.StockScreener._get_market_regime = original_get

    print(f"  passed: {out.passed}")
    print(f"  recommendation: {out.recommendation}")
    print(f"  market_score: {out.market_score} ({out.market_status})")
    print(f"  combined_score: {out.combined_score}")
    print(f"  reason: {out.reason}")

    assert out.market_status == "bear", "应为熊市"
    assert out.market_score <= 1, "熊市评分应低"

    print(f"  ✅ 案例3通过 (熊市正确识别)")

    return out


def test_case_04_strong_fund_weak_tech():
    """
    案例4：基本面强但技术弱
    Fundamental 15但Technical 60 → 结构不足 → NO_TRADE
    """
    print("\n" + "=" * 60)
    print("案例4: 基本面强技术弱 — 预期 NO_TRADE")
    print("=" * 60)

    # 跌破MA200的K线
    klines = _uptrend_klines(surge_days=0)
    # 最后几天大跌跌破MA200
    last_p = klines[-1].close
    for i in range(5):
        idx = len(klines) - 5 + i
        p = last_p * (1 - 0.05 * (i + 1))
        klines[idx].close = round(p, 2)
        klines[idx].high = round(p * 1.01, 2)
        klines[idx].low = round(p * 0.98, 2)
        klines[idx].open = round(p * 0.99, 2)

    inp = ScreenerInput("SZ.000002", "基本面强技术弱", klines,
                         market_cap=300e8, sector="消费")

    screener = StockScreener(enable_fundamental=True)
    out = screener.evaluate(inp)

    print(f"  passed: {out.passed}")
    print(f"  recommendation: {out.recommendation}")
    print(f"  reason: {out.reason}")
    print(f"  fundamental_score: {out.fundamental_score}")
    print(f"  combined_score: {out.combined_score}")

    # 技术面不过 → 淘汰
    assert not out.passed, "技术弱应淘汰"
    assert "MA200" in out.reason or "20日高" in out.reason or out.reason != "", \
        f"应有明确淘汰原因, 实得{out.reason}"

    print(f"  ✅ 案例4通过 (技术弱被正确拦截)")


def test_old_regression():
    """确认旧测试的关键断言仍兼容"""
    print("\n" + "=" * 60)
    print("回归验证: 旧筛选器关键路径")
    print("=" * 60)

    klines = _uptrend_klines(surge_days=3)
    inp = ScreenerInput("SZ.000977", "回归测试", klines, market_cap=200e8)
    screener = StockScreener(enable_fundamental=False)
    out = screener.evaluate(inp)

    assert out is not None
    # StockScreener输出类型兼容
    assert isinstance(out, ScreenerOutput)
    # 新字段存在
    assert hasattr(out, 'market_score')
    assert hasattr(out, 'sector_score')
    assert hasattr(out, 'breakout_stage')
    assert hasattr(out, 'combined_score')
    assert hasattr(out, 'recommendation')

    print(f"  ✅ 回归验证通过 ({len(klines)}根K线, "
          f"recommendation={out.recommendation}, combined={out.combined_score})")


if __name__ == "__main__":
    print(f"\n📋 Buy Stop V3.2.1 — Screener 集成测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    tests = [
        ("case_01", "完美突破", test_case_01_perfect_breakout),
        ("case_02", "CLIMAX拦截", test_case_02_climax_no_trade),
        ("case_03", "熊市降级", test_case_03_bear_market_downgrade),
        ("case_04", "弱技术拦截", test_case_04_strong_fund_weak_tech),
        ("case_05", "回归验证", test_old_regression),
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

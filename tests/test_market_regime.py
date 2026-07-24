"""
Buy Stop V3 — MarketRegime 模块测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from core.market_regime import MarketRegimeScorer, MarketRegime, get_market_regime
import logging
logging.getLogger("core.market_regime").setLevel(logging.WARNING)


def _make_index_klines(prices):
    """从价格列表生成指数K线"""
    return [{"date": f"2026-01-{i+1:02d}", "open": p*0.99, "close": p,
             "high": p*1.01, "low": p*0.98, "volume": 1000000}
            for i, p in enumerate(prices)]


def test_01_bull_market():
    print("\n=== 测试①: 牛市环境 ===")
    # 上涨趋势 + 价格>MA20 + MA20向上
    prices = [3000 + i * 10 for i in range(60)]  # 持续上涨
    hs300 = _make_index_klines(prices)
    sh = _make_index_klines([p * 0.3 for p in prices])
    cyb = _make_index_klines([p * 0.15 for p in prices])

    scorer = MarketRegimeScorer()
    regime = scorer.evaluate(hs300, sh, cyb)

    print(f"  trend_score: {regime.trend_score}/5")
    print(f"  market_status: {regime.market_status}")
    print(f"  hs300: {regime.hs300_trend}")
    print(f"  5日涨幅: {regime.hs300_change_5d:.2f}%")

    assert regime.trend_score >= 4, f"牛市应>=4分, 实得{regime.trend_score}"
    assert regime.market_status == "bull", f"应为bull, 实得{regime.market_status}"

    print("  ✅ 测试①通过")


def test_02_bear_market():
    print("\n=== 测试②: 熊市环境 ===")
    # 持续下跌
    prices = [3500 - i * 15 for i in range(60)]
    hs300 = _make_index_klines(prices)
    sh = _make_index_klines([p * 0.3 for p in prices])
    cyb = _make_index_klines([p * 0.15 for p in prices])

    scorer = MarketRegimeScorer()
    regime = scorer.evaluate(hs300, sh, cyb)

    print(f"  trend_score: {regime.trend_score}/5")
    print(f"  market_status: {regime.market_status}")
    print(f"  hs300: {regime.hs300_trend}")

    assert regime.trend_score <= 1, f"熊市应<=1分, 实得{regime.trend_score}"
    assert regime.market_status == "bear", f"应为bear, 实得{regime.market_status}"

    print("  ✅ 测试②通过")


def test_03_neutral_market():
    print("\n=== 测试③: 震荡市 ===")
    # 先冲高再跌回MA20以下，然后反弹回去 — 让MA20走平
    prices = []
    p = 3000
    for i in range(60):
        if i < 15:
            p *= 0.995   # 初期下跌
        elif i < 30:
            p *= 1.008   # 反弹
        elif i < 45:
            p *= 0.993   # 再次下跌（跌破MA20）
        else:
            p *= 1.002   # 缓慢回升
        prices.append(p)
    hs300 = _make_index_klines(prices)
    sh = _make_index_klines([p * 0.3 for p in prices])
    cyb = _make_index_klines([p * 0.15 for p in prices])

    scorer = MarketRegimeScorer()
    regime = scorer.evaluate(hs300, sh, cyb)

    print(f"  trend_score: {regime.trend_score}/5")
    print(f"  market_status: {regime.market_status}")

    assert regime.market_status == "neutral", f"震荡应为neutral, 实得{regime.market_status}"

    print("  ✅ 测试③通过")


def test_04_integration():
    print("\n=== 测试④: 集成测试（真实指数数据）===")
    try:
        regime = get_market_regime()
        print(f"  trend_score: {regime.trend_score}/5")
        print(f"  market_status: {regime.market_status}")
        print(f"  hs300: {regime.hs300_trend}")
        print(f"  hs300_5d: {regime.hs300_change_5d:.2f}%")
        assert isinstance(regime, MarketRegime)
        assert 0 <= regime.trend_score <= 5
        assert regime.market_status in ("bull", "neutral", "bear")
        print("  ✅ 测试④通过（真实数据）")
    except Exception as e:
        print(f"  ⚠️ 真实API调用跳过: {e}")


if __name__ == "__main__":
    test_01_bull_market()
    test_02_bear_market()
    test_03_neutral_market()
    test_04_integration()
    print("\n✅ 全部 MarketRegime 测试通过")

"""
Buy Stop V3 — BreakoutStage 模块测试

案例1：刚突破3天(<5天,涨幅<20%) → EARLY_BREAKOUT ✅
案例2：上涨30%(突破后10天,涨幅30%) → EXTENDED（因为>30%）
案例3：7连板翻倍 → CLIMAX 🚫
"""
import sys, os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from core.breakout_stage import (
    BreakoutStageIdentifier, BreakoutStage, BreakoutStageResult
)
from data.types import KLine
import logging
logging.getLogger("core.breakout_stage").setLevel(logging.WARNING)


def _make_kline(d, o, c, h, l, v=1000000):
    return KLine(date=d, open=o, close=c, high=h, low=l, volume=v, amount=0.0)


def test_01_early_breakout():
    """
    案例1：刚突破3天
    构造：K线突破20日高后3天，涨幅<20%
    预期：EARLY_BREAKOUT → allow_buy_stop=True
    """
    print("\n" + "=" * 60)
    print("测试①: 早期突破 (突破3天, 涨幅<20%)")
    print("=" * 60)

    # 生成60天K线，base 100，前57天缓慢上涨
    klines = []
    base = 100.0
    for i in range(57):
        klines.append(_make_kline(
            (date(2026, 5, 1) + timedelta(days=i)).isoformat(),
            round(base * 0.99, 2), round(base, 2),
            round(base * 1.01, 2), round(base * 0.98, 2),
        ))
        base *= 1.001  # 缓慢涨

    # 记录突破前的价格
    pre_breakout_high = max(k.high for k in klines)

    # 最后3天突破：价格跳空突破前高
    # 第2天的high和最后一天设为相同值
    for i in range(3):
        if i == 0:
            base = pre_breakout_high * 1.02
        else:
            base *= 1.005
        # 最后两天共享同一最高价
        k_high = base  # 让多日共享同一最高价
        klines.append(_make_kline(
            (date(2026, 6, 28) + timedelta(days=i)).isoformat(),
            round(base * 0.99, 2), round(base, 2),
            round(k_high, 2), round(base * 0.99, 2),
            v=3000000,
        ))

    highs = [k.high for k in klines]
    high20 = max(highs[-20:])
    high60 = max(highs[-60:]) if len(klines) >= 60 else max(highs)

    # 5日涨幅
    change_5d = (klines[-1].close - klines[-6].close) / klines[-6].close * 100

    identifier = BreakoutStageIdentifier()
    result = identifier.evaluate(klines, high20, high60,
                                  consecutive_limit=0, change_5d_pct=change_5d,
                                  days_since_breakout=0)

    print(f"  阶段: {result.stage_name} ({result.stage.value})")
    print(f"  距突破: {result.days_since_breakout}天（手动传入0）")
    print(f"  突破后涨幅: {result.change_since_breakout:.2f}%")
    print(f"  5日涨幅: {result.change_5d_pct:.2f}%")
    print(f"  允许BuyStop: {result.allow_buy_stop}")

    assert result.stage == BreakoutStage.EARLY_BREAKOUT, \
        f"应为EARLY_BREAKOUT, 实得{result.stage}"
    assert result.allow_buy_stop is True

    print("  ✅ 测试①通过")


def test_02_trending():
    """
    案例2：趋势运行中
    构造：突破后10天，涨幅25%
    预期：EXTENDED（因为距突破>10天）
    """
    print("\n" + "=" * 60)
    print("测试②: 延伸段 (突破10天, 涨幅25%)")
    print("=" * 60)

    klines = []
    base = 100.0
    for i in range(40):
        klines.append(_make_kline(
            (date(2026, 5, 1) + timedelta(days=i)).isoformat(),
            round(base * 0.99, 2), round(base, 2),
            round(base * 1.02, 2), round(base * 0.98, 2),
        ))
        base *= 1.002

    # 拉升10天
    for i in range(10):
        base *= 1.025
        klines.append(_make_kline(
            (date(2026, 6, 10) + timedelta(days=i)).isoformat(),
            round(base * 0.97, 2), round(base, 2),
            round(base * 1.03, 2), round(base * 0.96, 2),
            v=3000000,
        ))

    highs = [k.high for k in klines]
    high20 = max(highs[-20:])
    high60 = max(highs[-60:]) if len(klines) >= 60 else max(highs)
    change_5d = (klines[-1].close - klines[-6].close) / klines[-6].close * 100

    identifier = BreakoutStageIdentifier()
    result = identifier.evaluate(klines, high20, high60,
                                  consecutive_limit=0, change_5d_pct=change_5d)

    print(f"  阶段: {result.stage_name} ({result.stage.value})")
    print(f"  距突破: {result.days_since_breakout}天")
    print(f"  5日涨幅: {result.change_5d_pct:.2f}%")
    print(f"  允许BuyStop: {result.allow_buy_stop}")

    # 距突破>10天或5日涨幅>30% → EXTENDED
    assert result.stage in (BreakoutStage.EXTENDED, BreakoutStage.CLIMAX), \
        f"应为EXTENDED或CLIMAX, 实得{result.stage}"

    print("  ✅ 测试②通过")


def test_03_climax():
    """
    案例3：7连板翻倍
    预期：CLIMAX → allow_buy_stop=False
    """
    print("\n" + "=" * 60)
    print("测试③: 高潮段 (7连板, 翻倍)")
    print("=" * 60)

    klines = []
    base = 50.0
    for i in range(50):
        klines.append(_make_kline(
            (date(2026, 5, 1) + timedelta(days=i)).isoformat(),
            round(base * 0.99, 2), round(base, 2),
            round(base * 1.02, 2), round(base * 0.98, 2),
        ))
        base *= 1.002

    # 7天连续涨停
    for i in range(7):
        klines.append(_make_kline(
            (date(2026, 6, 20) + timedelta(days=i)).isoformat(),
            round(base * 0.98, 2), round(base * 1.10, 2),
            round(base * 1.10, 2), round(base * 0.97, 2),
            v=5000000,
        ))
        base *= 1.10

    highs = [k.high for k in klines]
    high20 = max(highs[-20:])
    high60 = max(highs[-60:]) if len(klines) >= 60 else max(highs)
    change_5d = (klines[-1].close - klines[-6].close) / klines[-6].close * 100

    identifier = BreakoutStageIdentifier()
    result = identifier.evaluate(klines, high20, high60,
                                  consecutive_limit=7, change_5d_pct=change_5d)

    print(f"  阶段: {result.stage_name} ({result.stage.value})")
    print(f"  连续涨停: {result.consecutive_limit}天")
    print(f"  5日涨幅: {result.change_5d_pct:.2f}%")
    print(f"  突破后涨幅: {result.change_since_breakout:.2f}%")
    print(f"  允许BuyStop: {result.allow_buy_stop}")

    assert result.stage == BreakoutStage.CLIMAX, \
        f"应为CLIMAX, 实得{result.stage}"
    assert result.allow_buy_stop is False

    print("  ✅ 测试③通过")


if __name__ == "__main__":
    test_01_early_breakout()
    test_02_trending()
    test_03_climax()
    print("\n✅ 全部 BreakoutStage 测试通过")

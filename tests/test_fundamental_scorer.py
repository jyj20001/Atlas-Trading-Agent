"""
Buy Stop V3 — fundamental_scorer 模块测试

测试内容：
  test_01_classify:       预告分类逻辑（预增/扭亏/预减）
  test_02_score_stock:    对真实股票评分（浪潮信息、贵州茅台）
  test_03_score_batch:    批量评分多只股票
  test_04_merge_score:    merge_fundamental_score 合并到 screener
  test_05_format_details: 格式化输出

用法：
  python test_fundamental_scorer.py
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from core.fundamental_scorer import (
    FundamentalScorer,
    merge_fundamental_score,
    format_fundamental_details,
)
from data.types import PerformanceForecast

import logging
logging.getLogger("data.cninfo_fetcher").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)


def test_01_classify():
    """测试① 预告分类逻辑"""
    print("\n" + "=" * 60)
    print("测试①: 预告分类逻辑")
    print("=" * 60)

    fs = FundamentalScorer()

    # 预增案例
    pf1 = PerformanceForecast(
        code="000977", name="浪潮信息", announce_date="2026-07-08",
        report_type="业绩预增", forecast_type="业绩预告",
        net_profit_lower=50000, net_profit_upper=70000,
        change_pct_lower=80, change_pct_upper=120,
    )
    cls1 = fs._classify_forecast(pf1)
    assert cls1["type"] == "预增", f"应分类为预增, 实得{cls1['type']}"
    print(f"  ✅ 预增分类正确: {cls1['type']} (变动中值={pf1.profit_change_pct}%)")

    # 扭亏案例
    pf2 = PerformanceForecast(
        code="000001", name="平安银行", announce_date="2026-07-15",
        report_type="扭亏为盈", forecast_type="业绩预告",
    )
    cls2 = fs._classify_forecast(pf2)
    assert cls2["type"] == "扭亏", f"应分类为扭亏, 实得{cls2['type']}"
    print(f"  ✅ 扭亏分类正确: {cls2['type']}")

    # 预减案例
    pf3 = PerformanceForecast(
        code="000002", name="万科A", announce_date="2026-07-20",
        report_type="业绩预减", forecast_type="业绩预告",
        change_pct_lower=-60, change_pct_upper=-40,
    )
    cls3 = fs._classify_forecast(pf3)
    assert cls3["type"] == "预减", f"应分类为预减, 实得{cls3['type']}"
    print(f"  ✅ 预减分类正确: {cls3['type']} (变动中值={pf3.profit_change_pct}%)")

    # 通过数据推断预增
    pf4 = PerformanceForecast(
        code="300750", name="宁德时代", announce_date="2026-07-10",
        report_type="业绩预告", forecast_type="业绩预告",
        change_pct_lower=40, change_pct_upper=60,
    )
    cls4 = fs._classify_forecast(pf4)
    assert cls4["type"] == "预增", f"数据驱动应分类为预增, 实得{cls4['type']}"
    print(f"  ✅ 数据驱动预增分类正确: {cls4['type']}")

    print(f"\n  ✅ 测试①全部通过")


def test_02_score_stock():
    """测试② 对真实股票评分"""
    print("\n" + "=" * 60)
    print("测试②: 真实股票基本面评分")
    print("=" * 60)

    fs = FundamentalScorer(lookback_days=90)

    # 浪潮信息
    result = fs.score_stock("000977", "浪潮信息")
    print(f"  浪潮信息(000977): 评分{result['score']}/15")
    for d in result.get("details", []):
        print(f"    ✅ {d}")
    for f in result.get("flags", []):
        print(f"    ⚠️ {f}")
    print(f"    预告/快报: {len(result.get('forecasts', []))} 条")
    print(f"    合同公告: {len(result.get('contracts', []))} 条")

    # 验证返回结构
    assert "score" in result, "应包含 score"
    assert "details" in result, "应包含 details"
    assert "flags" in result, "应包含 flags"
    assert 0 <= result["score"] <= 15, f"评分应在0~15之间, 实得{result['score']}"
    print(f"  ✅ 浪潮信息评分成功")

    # 贵州茅台
    result2 = fs.score_stock("600519", "贵州茅台")
    print(f"\n  贵州茅台(600519): 评分{result2['score']}/15")
    for d in result2.get("details", []):
        print(f"    ✅ {d}")
    assert 0 <= result2["score"] <= 15

    return result


def test_03_score_batch():
    """测试③ 批量评分多只股票"""
    print("\n" + "=" * 60)
    print("测试③: 批量评分多只股票")
    print("=" * 60)

    fs = FundamentalScorer(lookback_days=90)
    codes = ["000977", "600519", "300750", "002594", "000063"]

    results = []
    for code in codes:
        r = fs.score_stock(code)
        results.append(r)
        print(f"  {code}: {r['score']}/15  {r.get('details', [''])[0] if r['details'] else '无信号'}")

    assert len(results) == 5
    for r in results:
        assert 0 <= r["score"] <= 15

    print(f"  ✅ 批量评分全部成功")


def test_04_merge_score():
    """测试④ 合并到 screener 评分"""
    print("\n" + "=" * 60)
    print("测试④: merge_fundamental_score 合并")
    print("=" * 60)

    # 模拟 screener 评分
    screener_score = {
        "trend": 18,
        "structure": 22,
        "volume": 15,
        "turnover": 12,
        "risk": 8,
        "total": 75,
    }

    # 模拟基本面评分
    fundamental_score = {
        "score": 8,
        "details": ["业绩预增80%~120% (+8)"],
        "flags": [],
    }

    merged = merge_fundamental_score(screener_score, fundamental_score)

    assert "fundamental" in merged, "应包含 fundamental"
    assert merged["fundamental"] == 8, f"基本面分数应为8, 实得{merged['fundamental']}"
    assert merged["total"] == 75 + 8, f"总分应为83, 实得{merged['total']}"
    assert merged["trend"] == 18, "原分数不应被修改"

    print(f"  原总分: {screener_score['total']}")
    print(f"  基本面分: +{fundamental_score['score']}")
    print(f"  合并后总分: {merged['total']}")
    print(f"  ✅ merge 逻辑正确")


def test_05_format_details():
    """测试⑤ 格式化输出"""
    print("\n" + "=" * 60)
    print("测试⑤: 格式化输出")
    print("=" * 60)

    # 有详情
    score1 = {"score": 8, "details": ["业绩预增80% (+8)"], "flags": []}
    text1 = format_fundamental_details(score1)
    assert "业绩预增" in text1
    print(f"  有信号: {text1}")

    # 有风险标记
    score2 = {"score": 0, "details": [], "flags": ["业绩预减-60%"]}
    text2 = format_fundamental_details(score2)
    assert "预减" in text2
    print(f"  有风险: {text2}")

    # 无信号
    score3 = {"score": 0, "details": [], "flags": []}
    text3 = format_fundamental_details(score3)
    assert "无近期" in text3
    print(f"  无信号: {text3}")

    print(f"  ✅ 格式化输出正确")


# ── 主入口 ──

if __name__ == "__main__":
    print(f"\n📋 Buy Stop V3 — fundamental_scorer 测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    tests = [
        ("test_01", "预告分类", test_01_classify),
        ("test_02", "真实评分", test_02_score_stock),
        ("test_03", "批量评分", test_03_score_batch),
        ("test_04", "合并评分", test_04_merge_score),
        ("test_05", "格式化输出", test_05_format_details),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except AssertionError as e:
            print(f"  ❌ 失败: {e}")
            results[key] = False
        except Exception as e:
            import traceback
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            traceback.print_exc()
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)

    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total - passed} 失败")
    print(f"{'='*60}")

    if passed < total:
        sys.exit(1)

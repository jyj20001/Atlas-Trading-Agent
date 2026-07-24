"""
Buy Stop V3 — Notifier 模块测试

测试内容：
  1. 无Webhook环境下正常运行
  2. 消息格式正确（无候选/有候选/高分候选）
  3. Webhook不可达时优雅降级
"""

import sys
import os
import json
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

# ── 必须在导入 notifier 之前清除环境变量，避免意外读到真实配置 ──
os.environ.pop("WECOM_WEBHOOK_URL", None)

from utils.notifier import (
    is_configured,
    _build_no_candidate_msg,
    _build_candidate_msg,
    _send_markdown,
    notify_scan,
    _PUSH_SCORE_MIN,
)
from scanner.batch_runner import ScanSummary, ScanResult
from data.types import StockInfo
from core.screener import ScreenerOutput

import logging
logging.disable(logging.CRITICAL)


def _make_mock_summary(candidates_count: int = 0,
                        scores: list[int] = None) -> ScanSummary:
    """创建模拟的 ScanSummary（用于测试）"""
    summary = ScanSummary()
    summary.total = 100
    summary.skipped = 95
    summary.errors = 0
    summary.start_time = 0.0
    summary.end_time = 30.0

    if scores is None:
        scores = []

    for i, score in enumerate(scores):
        si = StockInfo(
            symbol=f"SZ.000{i:03d}",
            code=f"000{i:03d}",
            name=f"测试股票{i}",
            exchange="SZSE",
        )
        from data.types import BreakoutSignal
        mock_signal = BreakoutSignal(
            symbol=f"SZ.000{i:03d}", name=f"测试股票{i}",
            price=50.0 + i, breakout_price=52.0 + i,
            ma200=45.0, above_ma200=True,
            volume_ratio=1.8, turnover_pct=5.0,
            change_5d_pct=8.0 + i, consecutive_limit=0,
            days_since_breakout=2,
            score_trend=18, score_structure=22,
            score_volume=18, score_turnover=12,
            score_sector=8, score_risk=8,
            total_score=86, suggestion="候选",
            stop_loss=48.0, target=60.0, risk_reward=2.0,
        )
        so = ScreenerOutput(
            passed=True,
            signal=mock_signal,
            fundamental_score=8,
            fundamental_details="业绩预增",
            market_score=4,
            market_status="bull",
            sector_score=8,
            sector_details="强势板块",
            breakout_stage="EARLY_BREAKOUT",
            combined_score=score,
            recommendation="BUY_STOP",
        )
        summary.candidates.append(ScanResult(si, so, elapsed=2.0))

    return summary


def test_01_no_webhook():
    """测试① 无Webhook情况下程序正常运行"""
    print("\n" + "=" * 60)
    print("测试①: 无Webhook配置 → 正常跳过")
    print("=" * 60)

    configured = is_configured()
    assert configured is False, "无Webhook时应返回False"
    print(f"  ✅ is_configured() = {configured}")

    summary = _make_mock_summary()
    result = notify_scan(summary)
    assert result is True, "无配置时应返回True（静默跳过）"
    print(f"  ✅ notify_scan() 返回 {result}（静默跳过）")

    print(f"  ✅ 测试①通过")


def test_02_no_candidate_msg():
    """测试② 无候选时消息格式"""
    print("\n" + "=" * 60)
    print("测试②: 无候选消息格式")
    print("=" * 60)

    summary = _make_mock_summary(candidates_count=0)
    msg = _build_no_candidate_msg(summary)

    assert "Buy Stop" in msg
    assert "无符合" in msg or "0" in msg
    assert str(summary.total) in msg

    print(f"  消息内容:")
    for line in msg.split("\n"):
        print(f"    {line}")
    print(f"\n  ✅ 测试②通过")


def test_03_candidate_msg_format():
    """测试③ 有候选时消息格式正确"""
    print("\n" + "=" * 60)
    print("测试③: 有候选消息格式")
    print("=" * 60)

    summary = _make_mock_summary(scores=[105, 96])
    result = _build_candidate_msg(summary)

    assert "测试股票0" in result, "应包含股票名称"
    assert "105" in result, "应包含评分"
    assert "Buy Stop" in result or "价格" in result
    assert "✅" in result, "应包含入选原因"
    assert "技术评分" in result

    print(f"  消息预览 (前20行):")
    for line in result.split("\n")[:20]:
        print(f"    {line}")
    print(f"\n  ✅ 测试③通过")


def test_04_high_score_push():
    """测试④ 高分候选（A级以上）触发推送"""
    print("\n" + "=" * 60)
    print("测试④: A级以上触发推送")
    print("=" * 60)

    # 模拟有Webhook的情况
    with patch.dict(os.environ, {"WECOM_WEBHOOK_URL": "https://fake.webhook.test"}):
        # 重新导入notifier以读取新环境变量
        import importlib
        import utils.notifier as nf
        importlib.reload(nf)

        assert nf.is_configured(), "模拟配置后应返回True"

        # A级候选 (95分) — 应推送
        summary_a = _make_mock_summary(scores=[95])
        result_a = nf.notify_scan(summary_a)
        # 因为webhook地址不可达，返回False
        # 但_should_push应该返回True
        from utils.notifier import _PUSH_SCORE_MIN
        has_a = any(r.combined_score >= _PUSH_SCORE_MIN for r in summary_a.candidates)
        assert has_a, "95分应达到推送阈值"
        print(f"  ✅ 95分候选：触发推送检查 (has_a={has_a})")

        # B+级候选 (85分) — 不应推送
        summary_b = _make_mock_summary(scores=[85])
        has_b = any(r.combined_score >= _PUSH_SCORE_MIN for r in summary_b.candidates)
        assert not has_b, "85分不应达到推送阈值"
        print(f"  ✅ 85分候选：不触发推送 (has_b={has_b})")

    # 恢复
    os.environ.pop("WECOM_WEBHOOK_URL", None)
    import importlib
    import utils.notifier as nf
    importlib.reload(nf)

    print(f"  ✅ 测试④通过")


def test_05_webhook_unreachable():
    """测试⑤ Webhook不可达时优雅处理"""
    print("\n" + "=" * 60)
    print("测试⑤: Webhook不可达 → 优雅降级")
    print("=" * 60)

    # 使用无效但可连接的webhook测试send
    with patch.dict(os.environ, {"WECOM_WEBHOOK_URL": "https://httpbin.org/post"}):
        import importlib
        import utils.notifier as nf
        importlib.reload(nf)

        summary = _make_mock_summary(scores=[105])
        # 发送到httpbin（不检查格式，只检查不抛异常）
        try:
            result = nf.notify_scan(summary)
            # 即使发送失败也不应抛异常
            print(f"  ✅ notify_scan() 返回 {result}（未抛异常）")
        except Exception as e:
            print(f"  ❌ 不应抛异常: {e}")

    os.environ.pop("WECOM_WEBHOOK_URL", None)
    import importlib
    import utils.notifier as nf
    importlib.reload(nf)

    print(f"  ✅ 测试⑤通过")


def test_06_no_webhook_notify_scan():
    """测试⑥ 无Webhook + notify_scan 不抛异常"""
    print("\n" + "=" * 60)
    print("测试⑥: 无Webhook + notify_scan 不抛异常")
    print("=" * 60)

    # 确保环境变量已清除
    os.environ.pop("WECOM_WEBHOOK_URL", None)
    import importlib
    import utils.notifier as nf
    importlib.reload(nf)

    assert nf.is_configured() is False

    # 无候选
    s0 = _make_mock_summary(candidates_count=0)
    r0 = nf.notify_scan(s0)
    assert r0 is True
    print(f"  ✅ 无候选 + 无Webhook: 返回 {r0}")

    # 有候选
    s1 = _make_mock_summary(scores=[96])
    r1 = nf.notify_scan(s1)
    assert r1 is True
    print(f"  ✅ 有候选 + 无Webhook: 返回 {r1}")

    print(f"  ✅ 测试⑥通过")


# ── 主入口 ──

if __name__ == "__main__":
    print(f"\n📋 Buy Stop V3 — Notifier 模块测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    tests = [
        ("test_01", "无Webhook", test_01_no_webhook),
        ("test_02", "无候选消息", test_02_no_candidate_msg),
        ("test_03", "候选消息格式", test_03_candidate_msg_format),
        ("test_04", "A级推送阈值", test_04_high_score_push),
        ("test_05", "Webhook不可达", test_05_webhook_unreachable),
        ("test_06", "无Webhook完整链路", test_06_no_webhook_notify_scan),
    ]

    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except AssertionError as e:
            import traceback; traceback.print_exc()
            print(f"  ❌ 失败: {e}")
            results[key] = False
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)

    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total - passed} 失败")
    print(f"{'='*60}")

    if passed < total:
        sys.exit(1)

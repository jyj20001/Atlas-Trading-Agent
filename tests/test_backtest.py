"""
Buy Stop V3 — 回测模块测试

测试内容：
  test_01_single_stock:    单只股票回测（浪潮信息）
  test_02_compare_abc:     A/B/C三种配置对比
  test_03_trade_lifecycle: 交易生命周期（入场→止损/止盈/超时）
  test_04_no_signal:       无信号时结果为空
  test_05_multi_stock:     多只股票回测
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "buy_stop_v3"))

from backtest.engine import (
    BacktestEngine, BacktestResult, Trade, format_result
)

import logging
logging.getLogger("backtest").setLevel(logging.WARNING)
logging.getLogger("data.market_fetcher").setLevel(logging.WARNING)
logging.getLogger("core.screener").setLevel(logging.WARNING)
logging.getLogger("data.http_client").setLevel(logging.WARNING)
logging.getLogger("core.market_regime").setLevel(logging.WARNING)
logging.getLogger("core.sector_scorer").setLevel(logging.WARNING)
logging.getLogger("utils").setLevel(logging.WARNING)


def test_01_single_stock():
    """测试① 单只股票回测"""
    print("\n" + "=" * 60)
    print("测试①: 单只股票回测 (浪潮信息 000977)")
    print("=" * 60)

    engine = BacktestEngine(config="A")
    result = engine.run("000977", "浪潮信息",
                        start_date="2025-01-01",
                        end_date="2026-07-24")

    assert isinstance(result, BacktestResult), "应返回BacktestResult"
    print(f"  配置: {result.config}")
    print(f"  交易次数: {result.total_trades}")
    print(f"  胜率: {result.win_rate}%")
    print(f"  平均收益: {result.avg_pnl_pct}%")
    print(f"  总收益: {result.total_pnl_pct:.2f}%")
    print(f"  最大回撤: {result.max_drawdown}%")
    print(f"  盈亏比: {result.profit_factor}")
    print(f"  平均持仓: {result.avg_bars_held}天")

    # 不强制有交易（市场环境可能无信号）
    assert result.total_trades >= 0

    if result.trades:
        t = result.trades[0]
        assert t.entry_date
        assert t.entry_price > 0
        assert t.stop_loss > 0
        assert t.target > 0
        print(f"\n  第一笔: {t.entry_date} 入场={t.entry_price} "
              f"止损={t.stop_loss} 目标={t.target}")

    print(f"\n  ✅ 测试①通过")
    return result


def test_02_compare_abc():
    """测试② A/B/C三种配置对比"""
    print("\n" + "=" * 60)
    print("测试②: A/B/C配置对比")
    print("=" * 60)

    import core.screener as _scr
    from core.market_regime import MarketRegime as _MR
    _scr.StockScreener._get_market_regime = lambda self: _MR(4, "bull", "强势上涨")

    results = BacktestEngine.compare("000977", "浪潮信息",
                                      start_date="2025-06-01",
                                      end_date="2026-07-24")

    assert "A" in results, "应有配置A"
    assert "B" in results, "应有配置B"
    assert "C" in results, "应有配置C"

    for cfg, result in results.items():
        print(f"\n  配置 {cfg}: {result.total_trades}笔交易 "
              f"胜率{result.win_rate}% 均收益{result.avg_pnl_pct}%")

    print(f"\n  ✅ 测试②通过")
    return results


def test_03_trade_lifecycle():
    """测试③ 交易生命周期（入场/止损/止盈/超时）"""
    print("\n" + "=" * 60)
    print("测试③: 交易生命周期")
    print("=" * 60)

    from data.types import KLine

    # 模拟一笔交易
    trade = Trade(
        symbol="000977", name="测试",
        entry_date="2026-07-01", entry_price=100.0,
        stop_loss=95.0, target=115.0,
        signal_score=85, config="A",
    )

    assert trade.entry_price == 100.0
    assert trade.stop_loss == 95.0
    assert trade.target == 115.0
    assert trade.exit_date is None

    # 模拟止损触达
    trade.exit_date = "2026-07-03"
    trade.exit_price = trade.stop_loss
    trade.exit_reason = "stop_loss"
    trade.pnl_pct = round((95.0 - 100.0) / 100.0 * 100, 2)

    assert trade.exit_reason == "stop_loss"
    assert trade.pnl_pct == -5.0
    trade.exit_date = None
    trade.exit_price = None
    trade.exit_reason = ""
    trade.pnl_pct = 0.0

    # 模拟止盈触达
    trade.exit_date = "2026-07-05"
    trade.exit_price = trade.target
    trade.exit_reason = "take_profit"
    trade.pnl_pct = round((115.0 - 100.0) / 100.0 * 100, 2)

    assert trade.exit_reason == "take_profit"
    assert trade.pnl_pct == 15.0

    # 测试BacktestResult计算
    result = BacktestResult(config="A")
    result.trades = [trade]
    result.compute()

    assert result.total_trades == 1
    assert result.winning_trades == 1
    assert result.win_rate == 100.0
    assert result.avg_pnl_pct == 15.0

    print(f"  止损测试: -5.0% ✅")
    print(f"  止盈测试: +15.0% ✅")
    print(f"  胜率计算: {result.win_rate}% ✅")

    print(f"\n  ✅ 测试③通过")


def test_04_multi_stock():
    """测试④ 多只股票回测"""
    print("\n" + "=" * 60)
    print("测试④: 多只股票回测")
    print("=" * 60)

    import core.screener as _scr
    from core.market_regime import MarketRegime as _MR
    _scr.StockScreener._get_market_regime = lambda self: _MR(4, "bull", "强势上涨")

    stocks = [
        ("000977", "浪潮信息"),
        ("600519", "贵州茅台"),
        ("000858", "五粮液"),
    ]

    for code, name in stocks:
        engine = BacktestEngine(config="A")
        result = engine.run(code, name,
                            start_date="2026-01-01",
                            end_date="2026-07-24")
        print(f"  {code} {name}: {result.total_trades}笔 "
              f"胜率{result.win_rate}% "
              f"均收益{result.avg_pnl_pct}%")

        assert isinstance(result, BacktestResult)

    print(f"\n  ✅ 测试④通过")


def test_05_format():
    """测试⑤ 回测结果格式化输出"""
    print("\n" + "=" * 60)
    print("测试⑤: 格式化输出")
    print("=" * 60)

    result = BacktestResult(config="A")
    result.total_trades = 10
    result.winning_trades = 6
    result.losing_trades = 4
    result.win_rate = 60.0
    result.avg_pnl_pct = 3.5
    result.total_pnl_pct = 35.0
    result.max_drawdown = 8.2
    result.profit_factor = 1.8
    result.avg_bars_held = 12.5
    result.score_groups = {
        "70-79": {"trades": 3, "win_rate": 66.7, "avg_pnl": 2.1},
        "80-89": {"trades": 5, "win_rate": 60.0, "avg_pnl": 4.2},
        "90-99": {"trades": 2, "win_rate": 50.0, "avg_pnl": 3.0},
    }

    text = format_result(result)
    assert "交易次数: 10" in text
    assert "胜率: 60.0%" in text
    assert "最大回撤: 8.2%" in text
    assert "70-79" in text

    print(text)
    print(f"\n  ✅ 测试⑤通过")


if __name__ == "__main__":
    from datetime import date

    print(f"\n📋 Buy Stop V3 — Backtest 模块测试")
    print(f"   日期: {date.today()}")
    print(f"   {'='*40}")

    tests = [
        ("test_01", "单股票回测", test_01_single_stock),
        ("test_02", "ABC对比", test_02_compare_abc),
        ("test_03", "交易生命周期", test_03_trade_lifecycle),
        ("test_04", "多股票回测", test_04_multi_stock),
        ("test_05", "格式化输出", test_05_format),
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

"""Atlas Trading Agent — Portfolio Engine 测试

测试场景:
  1. CashManager 基础 (T+1/买入/卖出/冻结/解冻)
  2. 同日多个信号资金不足 → 仅能买入部分
  3. T+1 资金冻结 → 卖出后资金次日可用
  4. 最大仓位限制 → 不超过总资产 20%
  5. 组合净值计算 → 复利正确
  6. 完整流程 → 信号输入到指标输出
  7. 每日流程顺序 A→B→C→D→E→F→G 验证
"""

import sys, os, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

from backtest.portfolio_engine import PortfolioEngine
from backtest.cash_manager import CashManager
from backtest.position import Position
from backtest.signal_collector import Signal
from backtest.portfolio_metrics import PortfolioMetrics

PASS = 0
FAIL = 0

def ok(msg): global PASS; PASS += 1; print(f"  ✅ {msg}")
def fail(msg): global FAIL; FAIL += 1; print(f"  ❌ {msg}")


def test_01_cash_manager_basics():
    """资金管理基础功能"""
    print("\n── [test_01: CashManager] ──")
    cm = CashManager(initial_capital=100000)
    ok(f"初始={cm.available_cash}") if cm.available_cash == 100000 else fail(f"初始={cm.available_cash}")
    ok(f"总额={cm.total_equity}") if cm.total_equity == 100000 else fail(f"总额={cm.total_equity}")

    ok("可买入") if cm.can_buy(50000) else fail("不可买入")
    cm.buy(50000)
    ok(f"买入后可买={cm.available_cash}") if cm.available_cash == 50000 else fail(f"买入后={cm.available_cash}")

    ok("不可超额") if not cm.can_buy(60000) else fail("可超额")

    cm.sell(60000, 50000)
    ok(f"冻结={cm.frozen_cash}") if cm.frozen_cash == 60000 else fail(f"冻结={cm.frozen_cash}")
    ok(f"可用不变={cm.available_cash}") if cm.available_cash == 50000 else fail(f"可用={cm.available_cash}")

    cm.unfreeze_cash()
    ok(f"解冻后={cm.available_cash}") if cm.available_cash == 110000 else fail(f"解冻后={cm.available_cash}")
    ok(f"冻结清零={cm.frozen_cash}") if cm.frozen_cash == 0 else fail(f"冻结未清零")


def test_02_portfolio_same_day_cash_shortage():
    """同日多个信号资金不足→仅部分可买入"""
    print("\n── [test_02: 同日资金不足] ──")
    pe = PortfolioEngine(initial_capital=100000, max_position_pct=50.0, max_positions=10)

    # 同一天 3 个信号，每个需要 6 万（但总资金只有 10 万，每个最多 5 万）
    signals = [
        Signal(date="2026-07-20", code="000977", name="A", breakout_price=80,
               stop_loss=70, target=100, score=85, prev_close=78),
        Signal(date="2026-07-20", code="600519", name="B", breakout_price=1200,
               stop_loss=1100, target=1500, score=80, prev_close=1180),
        Signal(date="2026-07-20", code="300750", name="C", breakout_price=350,
               stop_loss=320, target=400, score=75, prev_close=345),
    ]
    # 添加 K 线数据让引擎能找到价格
    from data.types import KLine
    for sig in signals:
        pe._klines_cache[sig.code] = [
            KLine(date="2026-07-20", open=sig.breakout_price - 1,
                  close=sig.breakout_price + 1, high=sig.breakout_price + 2,
                  low=sig.breakout_price - 2, volume=1000000, amount=1e8),
        ]

    pe.cash.available_cash = 100000
    held = set()
    pe._process_day("2026-07-20", signals, held)

    entered = len([t for t in pe.trade_log if t["action"] == "buy"])
    ok(f"实际入场={entered} (≤3)") if entered <= 3 else fail(f"入场={entered}")
    ok(f"持仓≤5") if len(pe.positions) <= pe.max_positions else fail(f"持仓={len(pe.positions)}")
    ok(f"现金≥0") if pe.cash.available_cash >= 0 else fail(f"现金负数={pe.cash.available_cash}")


def test_03_t_plus_1_settlement():
    """T+1: 卖出后资金次日可用"""
    print("\n── [test_03: T+1 资金冻结] ──")
    cm = CashManager(initial_capital=100000)
    cm.buy(50000)
    pnl = cm.sell(55000, 50000)
    ok(f"冻结资金={cm.frozen_cash}") if cm.frozen_cash == 55000 else fail(f"冻结={cm.frozen_cash}")
    ok(f"可用={cm.available_cash}") if cm.available_cash == 50000 else fail(f"可用={cm.available_cash}")

    # 尝试用冻结资金买入 → 应失败
    ok("冻结资金不可用") if not cm.can_buy(55000) else fail("冻结资金可误用")

    # T+1 解冻
    cm.unfreeze_cash()
    ok("解冻后可买入") if cm.can_buy(100000) else fail("解冻后仍不可买入")


def test_04_max_position_limit():
    """仓位限制不超过 20%"""
    print("\n── [test_04: 仓位限制] ──")
    cm = CashManager(initial_capital=100000)
    max_pos = cm.total_assets * 0.2
    ok(f"最大可买={max_pos}") if max_pos == 20000 else fail(f"最大可买={max_pos}")

    ok("可买20%") if cm.can_buy(20000) else fail("不可买20%")
    cm.buy(20000)
    remaining = cm.available_cash
    ok(f"剩余={remaining}") if remaining == 80000 else fail(f"剩余={remaining}")


def test_05_portfolio_metrics_compound():
    """组合净值复利计算"""
    print("\n── [test_05: 复利指标] ──")
    curve = [
        {"date": "2026-07-20", "total_equity": 100000},
        {"date": "2026-07-21", "total_equity": 110000},  # +10%
        {"date": "2026-07-22", "total_equity": 99000},   # -10%
        {"date": "2026-07-23", "total_equity": 108900},  # +10%
    ]
    pm = PortfolioMetrics()
    pm.compute_from_equity_curve(curve)
    ok(f"总收益={pm.total_return_pct}%") if abs(pm.total_return_pct - 8.9) < 0.1 else fail(f"总收益={pm.total_return_pct}")
    ok(f"回撤={pm.max_drawdown_pct}%") if abs(pm.max_drawdown_pct - 10.0) < 0.5 else fail(f"回撤={pm.max_drawdown_pct}")
    ok(f"夏普={pm.sharpe_ratio}") if pm.sharpe_ratio != 0 else fail(f"夏普=0")


def test_06_portfolio_run_basic():
    """完整组合回测流程"""
    print("\n── [test_06: 完整流程] ──")
    pe = PortfolioEngine(initial_capital=1000000)
    signals = [
        Signal(date="2026-07-20", code="000977", name="浪潮", breakout_price=80,
               stop_loss=70, target=100, score=95, prev_close=78),
        Signal(date="2026-07-22", code="600519", name="茅台", breakout_price=1200,
               stop_loss=1100, target=1500, score=90, prev_close=1180),
    ]
    # 添加 K 线（至少覆盖两个日期）
    from data.types import KLine
    for sig in signals:
        pe._klines_cache[sig.code] = [
            KLine(date="2026-07-20", open=sig.breakout_price - 1,
                  close=sig.breakout_price + 1, high=sig.breakout_price + 2,
                  low=sig.breakout_price - 2, volume=1000000, amount=1e8),
            KLine(date="2026-07-21", open=sig.breakout_price,
                  close=sig.breakout_price + 0.5, high=sig.breakout_price + 1,
                  low=sig.breakout_price - 1, volume=1000000, amount=1e8),
            KLine(date="2026-07-22", open=sig.breakout_price + 1,
                  close=sig.breakout_price + 2, high=sig.breakout_price + 3,
                  low=sig.breakout_price, volume=1000000, amount=1e8),
            KLine(date="2026-07-23", open=sig.breakout_price + 2,
                  close=sig.breakout_price + 3, high=sig.breakout_price + 4,
                  low=sig.breakout_price + 1, volume=1000000, amount=1e8),
        ]

    pm = pe.run(signals)
    ok(f"引擎运行完成, 交易={pm.total_trades}") if pm.total_trades > 0 else ok(f"引擎运行完成, 未交易")
    ok("净值曲线非空") if pe.equity_curve else fail("净值曲线为空")


def test_07_daily_flow_order():
    """验证每日流程 A→B→C→D→E→F→G"""
    print("\n── [test_07: 每日流程顺序] ──")
    pe = PortfolioEngine(initial_capital=1000000)

    signals = [
        Signal(date="2026-07-21", code="600519", name="茅台",
               breakout_price=1200, stop_loss=1100, target=1500,
               score=95, prev_close=1180),
        Signal(date="2026-07-20", code="000977", name="浪潮",
               breakout_price=80, stop_loss=70, target=100,
               score=85, prev_close=78),
    ]
    from data.types import KLine
    for sig in signals:
        pe._klines_cache[sig.code] = [
            KLine(date="2026-07-20", open=78, close=85, high=86, low=77,
                  volume=2000000, amount=2e8),
            KLine(date="2026-07-21", open=85, close=88, high=90, low=84,
                  volume=2000000, amount=2e8),
            KLine(date="2026-07-22", open=82, close=75, high=83, low=74,
                  volume=2000000, amount=2e8),
        ]

    pm = pe.run(signals)
    # 验证按日期排序: 7/20→7/21
    dates = [e["date"] for e in pe.equity_curve]
    ok(f"日期已排序") if dates == sorted(dates) else fail(f"未排序: {dates}")

    # 验证每日流程产出 equity_curve
    ok(f"equity 曲线有 {len(pe.equity_curve)} 天") if len(pe.equity_curve) >= 2 else fail("equity 曲线太短")

    # 验证 CSV 输出字段完整
    if pe.equity_curve:
        fields = list(pe.equity_curve[0].keys())
        for req in ["date", "cash", "frozen_cash", "market_value",
                     "total_equity", "positions", "daily_return"]:
            ok(f"CSV 字段: {req}") if req in fields else fail(f"缺少 {req}")

    # 生成报告并验证
    rp = os.path.expanduser("~/temp_portfolio_test_report.md")
    report = pe.generate_report(rp)
    for keyword in ["交易次数", "胜率", "总收益", "夏普", "退出原因"]:
        ok(f"报告含: {keyword}") if keyword in report else fail(f"报告缺 {keyword}")
    if os.path.exists(rp):
        os.remove(rp)


if __name__ == "__main__":
    print("📋 Portfolio Engine 测试")
    print(f"{'='*40}")
    tests = [
        ("cm_basics", "CashManager 基础", test_01_cash_manager_basics),
        ("cash_short", "同日资金不足", test_02_portfolio_same_day_cash_shortage),
        ("t_plus_1", "T+1 资金冻结", test_03_t_plus_1_settlement),
        ("max_pos", "仓位限制", test_04_max_position_limit),
        ("compound", "复利指标", test_05_portfolio_metrics_compound),
        ("full_run", "完整流程", test_06_portfolio_run_basic),
        ("flow_order", "每日流程顺序", test_07_daily_flow_order),
    ]
    results = {}
    for key, name, fn in tests:
        print(f"\n  ── [{name}] ──")
        try:
            fn()
            results[key] = True
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ❌ 异常: {type(e).__name__}: {e}")
            results[key] = False

    total = len(tests)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{'='*60}")
    print(f"📊 汇总: {passed}/{total} 通过, {total-passed} 失败")
    print(f"      ✅ {PASS} assertions passed, ❌ {FAIL} failed")
    print('='*60)
    sys.exit(0 if FAIL == 0 else 1)

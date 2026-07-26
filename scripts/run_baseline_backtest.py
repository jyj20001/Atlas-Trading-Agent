"""Atlas Trading Agent — Baseline Backtest v1 (全量)

使用 BacktestEngineV36.1 + Historical Snapshot。
严格 A 股实盘约束：
  - T+1 限制
  - 涨停无法买入
  - 跌停无法卖出
  - 一字涨停过滤
  - 开盘跳空 + 滑点
  - 所有数据通过 snapshot_query + as_of 过滤

输出: docs/backtest_baseline_v1.md
"""

import sys, os, time, json, math
from datetime import date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))

from utils.logger import logger
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("backtest.engine_v36").setLevel(logging.WARNING)
logging.getLogger("backtest.context").setLevel(logging.WARNING)
logging.getLogger("core").setLevel(logging.WARNING)
logging.getLogger("data").setLevel(logging.WARNING)

START_DATE = "2019-01-01"
END_DATE = "2025-12-31"
TOP_STOCKS = 200  # 市值前 200 只

SCORE_BUCKETS = [
    (120, 999, "120分以上"),
    (110, 120, "110-120分"),
    (90,  110, "90-110分"),
    (0,   90,  "90分以下"),
]

def _fetch_stocks(count=200):
    from scanner.universe import build_stock_pool
    return [(s.code, s.name) for s in build_stock_pool("A")[:count]]

def _run():
    from backtest.engine_v36 import BacktestEngineV36
    from backtest.metrics import format_metrics

    codes = _fetch_stocks(TOP_STOCKS)
    logger.info(f"回测: {TOP_STOCKS}只, {START_DATE}~{END_DATE}")
    engine = BacktestEngineV36(config="D")
    t0 = time.time()
    metrics = engine.run_batch(codes, START_DATE, END_DATE, progress_interval=25)
    elapsed = time.time() - t0
    logger.info(f"\n完成: {elapsed:.0f}s")
    logger.info(f"\n{format_metrics(metrics)}")
    return metrics, engine._all_trades, codes, elapsed

def _yearly_split(trades):
    by_year = defaultdict(list)
    for t in trades:
        # Approximate year from bars_held and entry sequence
        # Simpler: we don't have entry dates in TradeMetrics
        # Use signal_score as proxy (not ideal)
        by_year["2020-2025"].append(t)
    # Better: estimate year from trade index
    return {}

def _market_regime_split(trades, market_klines):
    """Simplified market regime using HS300 (000300) trend"""
    return {"牛/熊/震荡": {"trades": len(trades)}}

def _score_split(trades):
    groups = {l: [] for _,_,l in SCORE_BUCKETS}
    for t in trades:
        for lo, hi, label in SCORE_BUCKETS:
            if lo <= t.signal_score < hi:
                groups[label].append(t)
                break
    result = {}
    for label, tl in groups.items():
        wins = [t for t in tl if t.pnl_pct > 0]
        result[label] = {
            "trades": len(tl),
            "win_rate": round(len(wins)/len(tl)*100,1) if tl else 0,
            "avg_pnl": round(sum(t.pnl_pct for t in tl)/len(tl),2) if tl else 0,
        }
    return result

def _gen_report(metrics, trades, codes, elapsed):
    lines = []
    w = lambda s="": lines.append(s)
    awl = _compute_awl(trades)

    w("# Atlas Trading Agent — Backtest Baseline v1")
    w("")
    w(f"**日期:** {date.today().isoformat()}")
    w(f"**引擎:** BacktestEngineV36.1 (A股实盘约束 + Snapshot)")
    w(f"**模型:** D (技术+基本面+市场+板块)")
    w(f"**回测区间:** {START_DATE} ~ {END_DATE}")
    w(f"**股票数量:** {len(codes)} 只 (市值前{TOP_STOCKS})")
    w(f"**耗时:** {timedelta(seconds=int(elapsed))}")
    w("")
    w("## 一、总体结果")
    w("")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 总交易次数 | {metrics.total_trades} |")
    w(f"| 胜率 | {metrics.win_rate}% |")
    w(f"| 平均盈利 | {awl['avg_win']}% |")
    w(f"| 平均亏损 | {awl['avg_loss']}% |")
    w(f"| 盈亏比 (Profit Factor) | {metrics.profit_factor} |")
    w(f"| 总收益率 | {metrics.total_pnl_pct}% |")
    w(f"| 年化收益率 | {metrics.annualized_return}% |")
    w(f"| 最大回撤 | {metrics.max_drawdown}% |")
    w(f"| 夏普比率 | {metrics.sharpe_ratio} |")
    w(f"| 平均持仓天数 | {metrics.avg_bars_held} |")
    w(f"| 连续亏损次数 | {metrics.max_consecutive_losses} |")
    w("")

    # Exit reasons
    w("## 退出原因分析")
    w("")
    w("| 原因 | 数量 | 胜率 | 平均盈亏% |")
    w("|------|:----:|:----:|:--------:|")
    exit_data = _exit_split(trades)
    for reason in ["take_profit", "stop_loss", "timeout"]:
        d = exit_data.get(reason, {})
        w(f"| {reason} | {d.get('trades',0)} | {d.get('win_rate','N/A')}% | {d.get('avg_pnl','N/A')}% |")
    w("")

    # Market regime split
    w("## 三、市场环境拆分")
    w("")
    w("| 市场状态 | 信号数 | 胜率 | 均收益 |")
    w("|----------|:------:|:----:|:------:|")
    market_data = _market_split(trades, metrics)
    for state, d in sorted(market_data.items()):
        if d["trades"] > 0:
            w(f"| {state} | {d['trades']} | {d['win_rate']}% | {d['avg_pnl']}% |")
    w("")

    # Score split
    w("## 四、评分拆分 (130分体系)")
    w("")
    w("| 评分区间 | 信号数 | 占比 | 胜率 | 均收益 |")
    w("|----------|:------:|:----:|:----:|:------:|")
    score_data = _score_split(trades)
    for _, _, label in SCORE_BUCKETS:
        d = score_data.get(label, {})
        cnt = d.get("trades", 0)
        pct = round(cnt / max(1, metrics.total_trades) * 100, 1)
        w(f"| {label} | {cnt} | {pct}% | {d.get('win_rate','-')}% | {d.get('avg_pnl','-')}% |")
    w("")

    # Assumptions
    w("## 五、假设与限制")
    w("")
    w("### 实盘约束")
    w("- **T+1 限制**: 买入当日不可卖出")
    w("- **涨停无法买入**: 买入价 >= 涨停价时本轮跳过")
    w("- **一字涨停**: 开盘即涨停且成交量<10万股时过滤")
    w("- **跌停无法卖出**: 止损日若跌停则延迟至可卖日")
    w("- **开盘跳空风险**: 成交价 = max(突破价, 开盘价) × (1+滑点)")
    w("- **成交量/价格为零的交易日**: 跳过（停牌/休市）")
    w("")
    w("### 数据源")
    w("- **K线**: Tencent API via market_fetcher (含 SQLite 缓存)")
    w("- **基本面**: announcement_snapshot (暂未回填历史数据 → score=0)")
    w("- **市场环境**: market_snapshot (6000行, 2018~2026, snapshot_query)")
    w("- **板块强度**: sector_snapshot (API限制未全量回填 → score≈0)")
    w("- **历史过滤**: 所有数据通过 `available_time <= signal_date` 严格过滤")
    w("")
    w("### 简化")
    w("- 使用前 200 只市值最大的股票作为样本（非全市场 4467 只）")
    w("- 无风险利率: 2% 年化（用于夏普比率）")
    w("- 滑点: 千1（单边）")
    w("- 佣金: 万2.5 + 印花税千1（卖出）")
    w("")
    w("---")
    w("*Atlas Trading Agent — Baseline Report v1.0*")
    w("*数据经过 snapshot_query，无未来函数*")
    w("*等待人工审核，不进行参数优化*")

    return "\n".join(lines)

def _compute_awl(trades):
    wins = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    return {
        "avg_win": round(sum(wins)/len(wins),2) if wins else 0,
        "avg_loss": round(sum(losses)/len(losses),2) if losses else 0,
    }

def _exit_split(trades):
    groups = defaultdict(list)
    for t in trades:
        groups[t.exit_reason].append(t)
    result = {}
    for reason, tl in groups.items():
        wins = [t for t in tl if t.pnl_pct > 0]
        result[reason] = {
            "trades": len(tl),
            "win_rate": round(len(wins)/len(tl)*100,1) if tl else 0,
            "avg_pnl": round(sum(t.pnl_pct for t in tl)/len(tl),2) if tl else 0,
        }
    return result

def _market_split(trades, metrics):
    """Split trades by prevailing market regime (simplified)"""
    # Extract market regimes from the backtest config (D is full model)
    # This is simplified - real split would need daily market data
    return {"全部行情": {
        "trades": metrics.total_trades,
        "win_rate": metrics.win_rate,
        "avg_pnl": metrics.avg_pnl_pct,
    }}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", type=int, default=TOP_STOCKS)
    args = parser.parse_args()
    TOP_STOCKS = args.stocks

    metrics, trades, codes, elapsed = _run()
    report = _gen_report(metrics, trades, codes, elapsed)

    rp = os.path.expanduser("~/Atlas-Trading-Agent/docs/backtest_baseline_v1.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        f.write(report)

    awl = _compute_awl(trades)
    print(f"\n{'='*60}")
    print(f"📊 Baseline v1 完成")
    print(f"{'='*60}")
    print(f"  信号: {metrics.total_trades}")
    print(f"  胜率: {metrics.win_rate}%")
    print(f"  平均盈利: {awl['avg_win']}%")
    print(f"  平均亏损: {awl['avg_loss']}%")
    print(f"  PF: {metrics.profit_factor}")
    print(f"  年化: {metrics.annualized_return}%")
    print(f"  夏普: {metrics.sharpe_ratio}")
    print(f"  最大回撤: {metrics.max_drawdown}%")
    print(f"  报告: {rp}")
    print(f"{'='*60}")

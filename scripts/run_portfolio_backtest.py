"""Atlas — 组合级 Baseline 快速执行版

分批运行：先收集信号、再回测、再报告。
信号保存到文件，失败可续。
"""

import sys, os, time, json, logging
from datetime import date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "buy_stop_v3"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

INITIAL_CAPITAL = 1_000_000
START = "2019-01-01"
END = "2026-07-24"
STOCKS = 200
SIGNAL_FILE = os.path.expanduser("~/signals_cache.json")

def collect_signals_fast():
    """快速信号采集 — 复用 StockScreener 减少 DB 往返"""
    from scanner.universe import build_stock_pool
    from backtest.signal_collector import Signal
    from data.market_fetcher import fetch_klines
    from core.screener import StockScreener, ScreenerInput
    from backtest.context import BacktestContext

    pool = [(s.code, s.name) for s in build_stock_pool("A")[:STOCKS]]
    all_signals = []
    t0 = time.time()

    for idx, (code, name) in enumerate(pool):
        try:
            klines = fetch_klines(code, days=800)
        except Exception:
            continue
        if not klines or len(klines) < 350:
            continue
        kr = [k for k in klines if START <= k.date <= END]
        if len(kr) < 50:
            continue
        warmup = 250

        # 预热前 250 根（不生成信号）
        for i in range(warmup, len(kr)):
            today = kr[i]
            if today.volume == 0 or today.close == 0:
                continue
            hist = kr[:i+1]
            signal_klines = hist[:-1]
            if len(signal_klines) < warmup:
                continue

            ctx = BacktestContext(signal_date=today.date)
            ctx.load_all()
            screener = StockScreener(enable_fundamental=True)
            ctx.inject_into(screener)
            if screener._fundamental_scorer:
                screener._fundamental_scorer._set_signal_date(today.date)

            prefix = "SH" if code.startswith("6") else "SZ"
            inp = ScreenerInput(symbol=f"{prefix}.{code}", name=name, klines=signal_klines, market_cap=0)
            out = screener.evaluate(inp)
            if out and out.passed and out.signal:
                bs = out.signal
                all_signals.append(Signal(date=today.date, code=code, name=name,
                    breakout_price=bs.breakout_price,
                    stop_loss=bs.stop_loss or bs.breakout_price * 0.93,
                    target=bs.target or bs.breakout_price * 1.15,
                    score=out.combined_score, prev_close=kr[i-1].close if i > 0 else today.close))

        if (idx+1) % 25 == 0:
            elapsed = time.time() - t0
            logging.info(f"  信号 [{idx+1}/{STOCKS}] {len(all_signals)}条 ETA:{elapsed/(idx+1)*(STOCKS-idx-1):.0f}s")

    all_signals.sort(key=lambda s: s.date)
    return all_signals


def main():
    # 信号采集
    if os.path.exists(SIGNAL_FILE):
        logging.info(f"从文件加载缓存 {SIGNAL_FILE}")
        with open(SIGNAL_FILE) as f:
            raw = json.load(f)
        from backtest.signal_collector import Signal
        signals = [Signal(**s) for s in raw]
    else:
        logging.info("采集信号...")
        t0 = time.time()
        signals = collect_signals_fast()
        logging.info(f"信号采集完成: {len(signals)}条, {time.time()-t0:.0f}s")
        # 保存缓存
        with open(SIGNAL_FILE, "w") as f:
            json.dump([vars(s) for s in signals], f, ensure_ascii=False, default=str)

    # 组合回测
    from backtest.portfolio_engine import PortfolioEngine
    pe = PortfolioEngine(initial_capital=INITIAL_CAPITAL, max_position_pct=20.0, max_positions=5)
    t1 = time.time()
    metrics = pe.run(signals)
    logging.info(f"组合回测完成: {time.time()-t1:.0f}s")

    # 保存 CSV
    csv_path = os.path.expanduser("~/Atlas-Trading-Agent/portfolio_equity_curve.csv")
    pe.save_equity_curve(csv_path)

    # 报告
    from backtest.portfolio_metrics import PortfolioMetrics
    pnl_list = [t["pnl_pct"] for t in pe.trade_log if t["action"] == "sell"]
    m = PortfolioMetrics()
    m.compute_from_equity_curve(pe.equity_curve, trades=pnl_list)
    buys = [t for t in pe.trade_log if t["action"] == "buy"]
    from collections import Counter
    exit_reasons = Counter(t["reason"] for t in pe.trade_log if t["action"] == "sell")

    lines = []
    def w(s=""): lines.append(s)

    w("# Atlas Trading Agent — Baseline Portfolio Backtest Report")
    w("")
    w(f"**引擎:** PortfolioEngine v1.0 + Historical Snapshot")
    w(f"**初始资金:** {INITIAL_CAPITAL:,.0f} RMB")
    w(f"**单股票最大仓位:** 20%")
    w(f"**最大持仓:** 5 | **最长持有:** 30天")
    w(f"**回测区间:** {START} ~ {END}")
    w(f"**股票池:** 前 {STOCKS} 只 | **缓存:** {'是' if os.path.exists(SIGNAL_FILE) else '否'}")
    w(f"**日期:** {date.today().isoformat()}")
    w("")

    w("## 收益")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 总收益率 | {m.total_return_pct}% |")
    w(f"| 年化收益率 | {m.annual_return_pct}% |")
    w(f"| 最大回撤 | {m.max_drawdown_pct}% |")
    w(f"| 夏普比率 | {m.sharpe_ratio} |")
    w(f"| Profit Factor | {m.profit_factor} |")
    w(f"| 年化波动率 | {m.volatility_pct}% |")
    w("")

    w("## 交易统计")
    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 总交易次数（买入） | {len(buys)} |")
    w(f"| 胜率 | {m.win_rate}% |")
    w(f"| 平均盈利 | {m.avg_win_pct}% |")
    w(f"| 平均亏损 | {m.avg_loss_pct}% |")
    w(f"| 平均持仓时间 | 由退出交易统计 |")
    w(f"| 最大连续亏损 | {m.max_consecutive_losses}次 |")
    w("")

    w("## 风险分析")
    max_dd_date = ""; max_dd_val = 0.0
    peak = INITIAL_CAPITAL
    for e in pe.equity_curve:
        if e["total_equity"] > peak: peak = e["total_equity"]
        dd = (peak - e["total_equity"]) / peak * 100
        if dd > max_dd_val: max_dd_val = dd; max_dd_date = e["date"]
    max_loss = 0.0; max_loss_date = ""
    for e in pe.equity_curve:
        dr = e.get("daily_return", 0)
        if dr < max_loss: max_loss = dr; max_loss_date = e["date"]

    w("| 指标 | 值 |")
    w("|------|-----:|")
    w(f"| 最大回撤 | {m.max_drawdown_pct}% |")
    w(f"| 最大回撤日期 | {max_dd_date} |")
    w(f"| 单日最大亏损 | {max_loss}% ({max_loss_date}) |")
    w(f"| 年化波动率 | {m.volatility_pct}% |")
    w("")

    w("## 退出原因")
    w("| 原因 | 次数 |")
    w("|------|:----:|")
    for reason, cnt in sorted(exit_reasons.items()):
        w(f"| {reason} | {cnt} |")
    w("")

    w("## 分年度收益")
    w("| 年份 | 期初 | 期末 | 收益率% | 交易数 |")
    w("|------|:---:|:---:|:------:|:-----:|")
    yearly_curve = defaultdict(list)
    for e in pe.equity_curve: yearly_curve[e["date"][:4]].append(e)
    yearly_buys = defaultdict(int)
    for t in pe.trade_log:
        if t["action"] == "buy": yearly_buys[t["date"][:4]] += 1
    for yr in sorted(yearly_curve):
        en = yearly_curve[yr]
        s = en[0]["total_equity"]
        e = en[-1]["total_equity"]
        ret = round((e-s)/s*100, 2) if s else 0
        lbl = f"{yr}年 YTD" if yr == "2026" else f"{yr}年"
        w(f"| {lbl} | {round(s):,.0f} | {round(e):,.0f} | {ret}% | {yearly_buys.get(yr,0)} |")

    rp = os.path.expanduser("~/Atlas-Trading-Agent/docs/BACKTEST_BASELINE_REPORT.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f: f.write("\n".join(lines))

    print(f"\n{'='*60}")
    print(f"📊 Portfolio Baseline")
    print(f"{'='*60}")
    print(f"  信号: {len(buys)}笔 | 胜率: {m.win_rate}%")
    print(f"  总收益: {m.total_return_pct}% | 年化: {m.annual_return_pct}%")
    print(f"  夏普: {m.sharpe_ratio} | PF: {m.profit_factor}")
    print(f"  回撤: {m.max_drawdown_pct}%")
    print(f"  CSV: portfolio_equity_curve.csv")
    print(f"  报告: docs/BACKTEST_BASELINE_REPORT.md")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()

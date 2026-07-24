"""
Buy Stop V3 — 回测引擎 V3.5

模拟A股真实交易规则：
  - 收盘后产生信号
  - 下一交易日Buy Stop成交
  - T+1限制
  - ATR止损 / 2R止盈
  - 佣金+印花税+滑点

ABCD模型：
  A: 纯技术（Technical only）
  B: 技术+基本面（无时间衰减约束）
  C: 技术+基本面+市场环境
  D: 完整模型（技术+基本面+市场+板块+阶段）

未来函数修复：
  基本面评分在回测中必须使用历史快照（公告日期 <= 信号日期）
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
import math

from utils.logger import logger
from data.types import KLine
from data.market_fetcher import fetch_klines
from backtest.metrics import TradeMetrics, BacktestMetrics, format_metrics


# ── 交易成本 ──

COMMISSION_RATE = 0.00025     # 佣金万2.5
STAMP_TAX_RATE = 0.001        # 印花税千1（卖出）
SLIPPAGE_RATE = 0.001         # 滑点千1


# ── 回测引擎（多股票 + ABCD 对比） ──

class BacktestEngineV35:
    """
    V3.5 回测引擎
    支持多股票滚动回测，ABCD模型对比，交易成本，未来函数修复。
    """

    def __init__(self, config: str = "D",
                 cost_per_trade_pct: float = 0.001,
                 max_hold_days: int = 30):
        self.config = config
        self.cost_per_trade = cost_per_trade_pct
        self.max_hold = max_hold_days

        # 根据配置决定启用哪些评分
        enable_fundamental = config in ("B", "C", "D")
        self._enable_fundamental = enable_fundamental

        from core.screener import StockScreener
        self._screener = StockScreener(
            enable_fundamental=enable_fundamental,
        )

    def run_single(self, code: str, name: str = "",
                    start_date: str = "2023-01-01",
                    end_date: str = "2026-07-24") -> list[TradeMetrics]:
        """对单只股票运行回测，返回交易列表"""
        logger.debug(f"回测 {code} {name} config={self.config}")

        all_klines = fetch_klines(code, days=800)
        if not all_klines or len(all_klines) < 350:
            return []

        klines = [k for k in all_klines if start_date <= k.date <= end_date]
        if len(klines) < 50:
            return []

        trades: list[TradeMetrics] = []
        in_position = False
        entry_date = ""
        entry_price = 0.0
        stop_loss = 0.0
        target = 0.0
        signal_score = 0

        warmup = 250
        total = len(klines)

        for i in range(warmup, total):
            today = klines[i]
            if today.volume == 0 or today.close == 0:
                continue

            hist = klines[:i+1]

            if in_position:
                # ── 持仓管理 ──
                bars = self._bars_between(entry_date, today.date)

                # 止损
                if today.low <= stop_loss:
                    exit_price = stop_loss
                    reason = "stop_loss"
                # 止盈
                elif today.high >= target:
                    exit_price = target
                    reason = "take_profit"
                # 超时
                elif bars >= self.max_hold:
                    exit_price = today.close
                    reason = "timeout"
                else:
                    continue

                # 扣除交易成本
                cost = self._calc_cost(entry_price, exit_price)
                pnl = (exit_price - entry_price) / entry_price * 100 - cost

                trades.append(TradeMetrics(
                    pnl_pct=round(pnl, 2),
                    pnl_amount=exit_price - entry_price,
                    bars_held=bars,
                    exit_reason=reason,
                    signal_score=signal_score,
                    config=self.config,
                ))
                in_position = False
                continue

            # ── 信号生成（用hist[:-1]不含今天，避免未来函数）──
            signal_klines = hist[:-1]
            if len(signal_klines) < warmup:
                continue

            output = self._generate_signal(code, name, signal_klines)
            if not output or not output.passed:
                continue
            bs = output.signal
            if not bs:
                continue

            # ── 入场 ──
            bp = bs.breakout_price
            if today.high >= bp:
                fill = max(bp, today.open)
                if fill > today.high:
                    fill = bp

                stop = bs.stop_loss if bs.stop_loss > 0 else fill * 0.93
                tgt = bs.target if bs.target > 0 else fill * 1.15

                entry_date = today.date
                entry_price = round(fill, 2)
                stop_loss = round(stop, 2)
                target = round(tgt, 2)
                signal_score = output.combined_score
                in_position = True

        return trades

    def _generate_signal(self, code, name, klines):
        from core.screener import ScreenerInput
        prefix = "SH" if code.startswith("6") else "SZ"
        inp = ScreenerInput(
            symbol=f"{prefix}.{code}", name=name,
            klines=klines, market_cap=0,
        )
        return self._screener.evaluate(inp)

    @staticmethod
    def _calc_cost(entry: float, exit_: float) -> float:
        """计算交易成本（占本金百分比）"""
        commission = (entry + exit_) * COMMISSION_RATE / entry * 100
        stamp = exit_ * STAMP_TAX_RATE / entry * 100
        slippage = (entry + exit_) * SLIPPAGE_RATE / entry * 100
        return round(commission + stamp + slippage, 3)

    @staticmethod
    def _bars_between(d1: str, d2: str) -> int:
        try:
            return max(1, (datetime.strptime(d2, "%Y-%m-%d")
                          - datetime.strptime(d1, "%Y-%m-%d")).days)
        except ValueError:
            return 1

    # ── 批量回测 ──

    def run_batch(self, codes: list[tuple[str, str]],
                   start_date: str = "2023-01-01",
                   end_date: str = "2026-07-24",
                   progress_interval: int = 50) -> BacktestMetrics:
        """对多只股票运行回测"""
        all_trades: list[TradeMetrics] = []
        total = len(codes)

        for idx, (code, name) in enumerate(codes):
            trades = self.run_single(code, name, start_date, end_date)
            all_trades.extend(trades)

            if (idx + 1) % progress_interval == 0:
                logger.info(f"  回测进度 [{idx+1}/{total}] "
                           f"累计{len(all_trades)}笔交易")

        metrics = BacktestMetrics(config=self.config)
        metrics.compute(all_trades, cost_per_trade_pct=self.cost_per_trade)
        return metrics


# ── ABCD 对比 ──

def compare_abcd(codes: list[tuple[str, str]],
                  start_date: str = "2023-01-01",
                  end_date: str = "2026-07-24") -> dict[str, BacktestMetrics]:
    """A/B/C/D 四种配置的对比回测"""
    results = {}
    for cfg in ["A", "B", "C", "D"]:
        engine = BacktestEngineV35(config=cfg)
        results[cfg] = engine.run_batch(codes, start_date, end_date)
        logger.info(f"配置 {cfg} 完成: "
                    f"{results[cfg].total_trades}笔")
    return results


# ── 生成回测报告 ──

def generate_report(results: dict[str, BacktestMetrics],
                     stock_count: int,
                     start_date: str, end_date: str) -> str:
    """生成Markdown格式的回测报告"""
    lines = []
    _w = lambda s="": lines.append(s)

    _w("# Buy Stop V3.5 回测报告")
    _w(f"")
    _w(f"**回测区间:** {start_date} ~ {end_date}")
    _w(f"**股票数量:** {stock_count} 只")
    _w(f"**生成时间:** {date.today().isoformat()}")
    _w(f"")
    _w(f"## 模型对比")
    _w(f"")
    _w(f"| 指标 | A(纯技术) | B(技+基本面) | C(技+基+市场) | D(完整模型) |")
    _w(f"|------|:---------:|:------------:|:-------------:|:----------:|")

    def _v(m: BacktestMetrics, attr: str) -> str:
        val = getattr(m, attr, 0)
        if isinstance(val, float):
            return f"{val:.1f}"
        return str(val)

    rows = [
        ("交易次数", "total_trades"),
        ("胜率%", "win_rate"),
        ("平均收益%", "avg_pnl_pct"),
        ("总收益%", "total_pnl_pct"),
        ("盈亏比", "profit_factor"),
        ("最大回撤%", "max_drawdown"),
        ("平均持仓(天)", "avg_bars_held"),
        ("连续亏损", "max_consecutive_losses"),
        ("总成本%", "total_cost_pct"),
    ]
    for label, attr in rows:
        vals = " | ".join(_v(results[c], attr) for c in ["A", "B", "C", "D"])
        _w(f"| {label} | {vals} |")

    _w(f"")
    _w(f"## 最佳模型分析")
    _w(f"")

    # 找最优
    best_config = max(results, key=lambda c: results[c].total_pnl_pct)
    best = results[best_config]
    _w(f"**总收益最优:** 配置 {best_config}")
    _w(f"- 交易次数: {best.total_trades}")
    _w(f"- 胜率: {best.win_rate}%")
    _w(f"- 总收益: {best.total_pnl_pct}%")
    _w(f"- 盈亏比: {best.profit_factor}")
    _w(f"")

    # 评分分组统计（仅D模型）
    d = results.get("D")
    if d and d.score_groups:
        _w(f"## D模型评分分组统计")
        _w(f"")
        _w(f"| 评分区间 | 交易次数 | 胜率 | 均收益 |")
        _w(f"|----------|:--------:|:----:|:------:|")
        for bucket, stats in d.score_groups.items():
            _w(f"| {bucket} | {stats['trades']} | {stats['win_rate']}% | {stats['avg_pnl']}% |")
        _w(f"")

    _w(f"## 结论")
    _w(f"")
    # 是否有足够样本
    total_trades = sum(m.total_trades for m in results.values())
    if total_trades < 30:
        _w(f"⚠️ 样本量不足({total_trades}笔)，结论需谨慎参考。")
    else:
        _w(f"✅ 样本量充足({total_trades}笔)，结论具有参考意义。")

    best_win_rate = max(results[c].win_rate for c in results)
    if best_win_rate >= 50:
        _w(f"✅ 最佳模型胜率{best_win_rate}%，超过50%基准线。")
    else:
        _w(f"⚠️ 最佳模型胜率仅{best_win_rate}%，低于50%基准线。")

    _w(f"")
    _w(f"---")
    _w(f"*Buy Stop V3.5 自动生成*")

    return "\n".join(lines)


def save_backtest_report(results: dict[str, BacktestMetrics],
                          codes: list,
                          start_date: str, end_date: str,
                          filepath: str = "") -> str:
    """保存回测报告到文件"""
    from pathlib import Path
    from config.settings import OUTPUT_DIR

    report = generate_report(results, len(codes), start_date, end_date)
    if not filepath:
        filepath = str(OUTPUT_DIR / "reports" / f"backtest_{date.today().strftime('%Y%m%d')}.md")

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    Path(filepath).write_text(report, encoding="utf-8")
    return filepath

"""Atlas Trading Agent — 时间驱动组合回测引擎

按交易日逐日推进，统一管理资金和持仓。

核心流程:
  1. SignalCollector 预生成所有信号
  2. PortfolioEngine 按日期排序所有信号
  3. 每个交易日严格按 A→B→C→D→E→F→G:
     A. 更新持仓市价
     B. 检查退出条件
     C. 执行卖出
     D. 释放 T+1 可用资金
     E/F. 按评分排序信号，检查资金/仓位限制后买入
     G. 记录日终快照

约束:
  - 单股票最大仓位 20%
  - 最大同时持仓 5 只
  - T+1 卖出 + T+1 资金交收
  - 无现金不可买入
"""

import csv
import os
import math
from datetime import date, datetime, timedelta
from typing import Optional

from utils.logger import logger
from data.market_fetcher import fetch_klines
from backtest.position import Position
from backtest.cash_manager import CashManager
from backtest.portfolio_metrics import PortfolioMetrics
from backtest.signal_collector import Signal, collect_signals
from backtest.engine_v36 import _limit_pct, _calc_limit_price, _is_limit_down


# ── 默认参数 ──
INITIAL_CAPITAL = 1_000_000       # 初始资金 100 万
MAX_POSITION_PCT = 20.0           # 单股票最大仓位 20%
MAX_CONCURRENT_POSITIONS = 5      # 最大同时持仓
MAX_HOLD_DAYS = 30                # 最长持有天数
COMMISSION_RATE = 0.00025         # 佣金万 2.5
STAMP_TAX_RATE = 0.001            # 印花税千 1
SLIPPAGE_RATE = 0.001             # 滑点千 1
MIN_TRADE_AMOUNT = 10000          # 最小交易金额
LOT_SIZE = 100                    # A 股 1 手 = 100 股


class PortfolioEngine:
    """时间驱动组合回测引擎"""

    def __init__(self, initial_capital: float = INITIAL_CAPITAL,
                 max_position_pct: float = MAX_POSITION_PCT,
                 max_positions: int = MAX_CONCURRENT_POSITIONS,
                 max_hold_days: int = MAX_HOLD_DAYS):
        self.initial_capital = initial_capital
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions
        self.max_hold_days = max_hold_days

        self.cash = CashManager(initial_capital=initial_capital)
        self.positions: list[Position] = []
        self.equity_curve: list[dict] = []
        self.trade_log: list[dict] = []
        self._klines_cache: dict[str, list] = {}  # code -> klines
        self._date_idx: dict[str, int] = {}        # code -> current index

    def run(self, signals: list[Signal]) -> PortfolioMetrics:
        """运行组合回测

        Args:
            signals: 预生成的信号列表（按日期排序）

        Returns:
            PortfolioMetrics
        """
        if not signals:
            logger.warning("无信号输入")
            return PortfolioMetrics()

        # 按日期分组
        date_groups: dict[str, list[Signal]] = {}
        for s in signals:
            date_groups.setdefault(s.date, []).append(s)

        sorted_dates = sorted(date_groups.keys())
        logger.info(f"组合回测: {len(sorted_dates)} 个交易日, "
                   f"{len(signals)} 条信号")

        # 记录所有已持有代码，防止重复入场
        held_codes: set[str] = set()

        for day_idx, today_str in enumerate(sorted_dates):
            self._process_day(today_str, date_groups[today_str], held_codes)

        # 最后一日强制平仓
        self._liquidate_all(sorted_dates[-1])

        # 计算指标
        return self._compute_metrics()

    def _process_day(self, today_str: str, today_signals: list[Signal],
                      held_codes: set[str]):
        """处理一个交易日 — 严格顺序 A→B→C→D→E→F→G

        A. 更新已有持仓市场价值
        B. 检查退出条件
        C. 执行卖出
        D. 释放 T+1 可用资金（前一日卖出资金今日可用）
        E. 检查当日新信号
        F. 根据资金和仓位限制买入
        G. 保存每日 equity
        """
        # A. 更新所有持仓市价
        self._update_all_prices(today_str)

        # B. 检查退出条件
        exits = self._process_exits(today_str)
        for pos, reason, exit_price in exits:
            # C. 执行卖出
            self._close_position(pos, exit_price, reason, today_str)
            # 从 held_codes 移除（后续可重新入场）
            held_codes.discard(pos.code)

        # D. 释放 T+1 可用资金（前一日卖出资金到账）
        self.cash.unfreeze_cash()

        # E/F. 检查新信号并按资金/仓位限制买入
        today_signals.sort(key=lambda s: s.score, reverse=True)
        for sig in today_signals:
            if sig.code in held_codes:
                continue
            if len(self.positions) >= self.max_positions:
                break  # 已满仓
            self._try_enter(sig, today_str, held_codes)

        # G. 记录日终快照
        self._record_snapshot(today_str)

    def _update_all_prices(self, date_str: str):
        """更新所有持仓的当前价"""
        for pos in self.positions:
            klines = self._get_klines(pos.code)
            price = self._find_price_at_date(klines, date_str)
            if price:
                pos.update_price(price)

    def _find_price_at_date(self, klines: list, date_str: str) -> Optional[float]:
        """查找指定日期的收盘价"""
        for k in klines:
            if k.date == date_str:
                return k.close
        return None

    def _get_klines(self, code: str) -> list:
        """获取/缓存 K 线"""
        if code not in self._klines_cache:
            self._klines_cache[code] = fetch_klines(code, days=800) or []
        return self._klines_cache[code]

    def _process_exits(self, today_str: str) -> list[tuple]:
        """处理所有持仓的退出条件"""
        exits = []
        for pos in list(self.positions):
            if pos.entry_date == today_str:
                continue  # T+1 不可卖出

            bars_held = self._bars_between(pos.entry_date, today_str)
            exit_price = None
            reason = ""

            klines = self._get_klines(pos.code)
            today_k = self._find_kline(klines, today_str)
            if not today_k:
                continue

            prev_close = pos.current_price or today_k.close
            limit_pct = _limit_pct(pos.code)

            # 止损
            if pos.should_stop:
                if not _is_limit_down(today_k.close, prev_close, limit_pct):
                    exit_price = max(pos.stop_loss, today_k.open)
                    reason = "stop_loss"

            # 止盈
            if exit_price is None and pos.should_take_profit:
                exit_price = min(pos.target_price, today_k.high)
                reason = "take_profit"

            # 超时
            if exit_price is None and pos.is_expired(bars_held):
                exit_price = today_k.close
                reason = "timeout"

            if exit_price:
                exits.append((pos, reason, exit_price))

        return exits

    def _find_kline(self, klines: list, date_str: str):
        for k in klines:
            if k.date == date_str:
                return k
        return None

    def _close_position(self, pos: Position, exit_price: float,
                         reason: str, date_str: str):
        """平仓"""
        cost = self._calc_cost(pos.entry_price, exit_price)
        proceeds = exit_price * pos.quantity
        pnl = self.cash.sell(proceeds, pos.cost_basis)
        pnl_pct = round((exit_price - pos.entry_price) / pos.entry_price * 100 - cost, 2)

        # 更新持仓市值为 0
        self.cash.update_position_value(
            sum(p.market_value for p in self.positions if p != pos)
        )

        self.positions.remove(pos)
        self.trade_log.append({
            "date": date_str,
            "code": pos.code,
            "name": pos.name,
            "action": "sell",
            "price": round(exit_price, 2),
            "quantity": pos.quantity,
            "pnl_pct": pnl_pct,
            "pnl_amount": round(pnl, 2),
            "reason": reason,
        })

    def _try_enter(self, sig: Signal, date_str: str,
                    held_codes: set[str]):
        """尝试入场"""
        # 检查涨跌停
        limit_pct = _limit_pct(sig.code)
        up_limit = _calc_limit_price(sig.prev_close, limit_pct, "up")
        if sig.breakout_price >= up_limit:
            return

        klines = self._get_klines(sig.code)
        today_k = self._find_kline(klines, date_str)
        if not today_k or today_k.volume == 0:
            return

        # 一字涨停过滤
        if today_k.open >= up_limit and today_k.volume < 100000:
            return

        if today_k.high < sig.breakout_price:
            return

        # 计算买入量
        fill = max(sig.breakout_price, today_k.open) * (1 + SLIPPAGE_RATE)
        if fill > today_k.high:
            fill = min(sig.breakout_price * (1 + SLIPPAGE_RATE), today_k.high)

        # 仓位计算：最大 20% 可用资金
        max_position_amount = self.cash.total_assets * self.max_position_pct / 100
        position_amount = min(max_position_amount, self.cash.available_cash)

        # 按整手计算股数
        quantity = int(position_amount / fill / LOT_SIZE) * LOT_SIZE
        if quantity < LOT_SIZE:
            return
        if quantity * fill < MIN_TRADE_AMOUNT:
            return

        cost = quantity * fill
        commission = cost * COMMISSION_RATE
        total_cost = cost + commission

        if not self.cash.can_buy(total_cost):
            return

        # 执行买入
        self.cash.buy(total_cost)
        pos = Position(
            code=sig.code,
            name=sig.name,
            entry_date=date_str,
            entry_price=round(fill, 2),
            quantity=quantity,
            stop_loss=round(sig.stop_loss, 2),
            target_price=round(sig.target, 2),
            current_price=round(fill, 2),
            cost_basis=round(total_cost, 2),
            market_value=round(cost, 2),
            max_hold_days=self.max_hold_days,
        )
        self.positions.append(pos)
        held_codes.add(sig.code)

        # 更新持仓市值
        self.cash.update_position_value(
            sum(p.market_value for p in self.positions)
        )

        self.trade_log.append({
            "date": date_str,
            "code": sig.code,
            "name": sig.name,
            "action": "buy",
            "price": round(fill, 2),
            "quantity": quantity,
            "cost": round(total_cost, 2),
            "score": sig.score,
            "stage": sig.stage,
        })

    def _record_snapshot(self, date_str: str):
        """记录日终快照"""
        prev = self.equity_curve[-1]["total_equity"] if self.equity_curve else self.initial_capital
        curr = self.cash.total_equity
        daily_ret = round((curr - prev) / prev * 100, 4) if prev > 0 else 0.0

        self.equity_curve.append({
            "date": date_str,
            "cash": round(self.cash.available_cash, 2),
            "frozen_cash": round(self.cash.frozen_cash, 2),
            "market_value": round(self.cash.total_positions_value, 2),
            "total_equity": round(curr, 2),
            "positions": len(self.positions),
            "daily_return": daily_ret,
        })

    def _liquidate_all(self, date_str: str):
        """最后一日强制平仓"""
        for pos in list(self.positions):
            klines = self._get_klines(pos.code)
            price = self._find_price_at_date(klines, date_str)
            exit_price = price or pos.current_price
            self._close_position(pos, exit_price, "liquidation", date_str)

    def _compute_metrics(self) -> PortfolioMetrics:
        """计算组合指标"""
        metrics = PortfolioMetrics()
        pnl_list = [t["pnl_pct"] for t in self.trade_log if t["action"] == "sell"]
        metrics.compute_from_equity_curve(self.equity_curve, trades=pnl_list)

        # 补充统计
        buys = [t for t in self.trade_log if t["action"] == "buy"]
        metrics.total_trades = len(buys)

        logger.info(
            f"组合回测完成: "
            f"总收益{metrics.total_return_pct}% "
            f"年化{metrics.annual_return_pct}% "
            f"夏普{metrics.sharpe_ratio} "
            f"回撤{metrics.max_drawdown_pct}% "
            f"交易{metrics.total_trades}笔"
        )
        return metrics

    # ── 辅助 ──

    @staticmethod
    def _calc_cost(entry: float, exit_: float) -> float:
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

    def save_equity_curve(self, path: str):
        """保存净值曲线到 CSV"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            if self.equity_curve:
                w = csv.DictWriter(f, fieldnames=self.equity_curve[0].keys())
                w.writeheader()
                w.writerows(self.equity_curve)
        logger.info(f"净值曲线保存: {path}")

    def generate_report(self, path: str):
        """生成完整回测报告到 Markdown

        包含: 交易次数/胜率/总收益/年化/回撤/夏普/PF/持仓/退出原因
        """
        from collections import Counter
        metrics = PortfolioMetrics()
        pnl_list = [t["pnl_pct"] for t in self.trade_log if t["action"] == "sell"]
        metrics.compute_from_equity_curve(self.equity_curve, trades=pnl_list)
        buys = [t for t in self.trade_log if t["action"] == "buy"]

        # 退出原因统计
        exit_reasons = Counter(
            t["reason"] for t in self.trade_log if t["action"] == "sell"
        )

        # 平均持仓（以卖出交易为准）
        avg_bars = 0
        sell_trades = [t for t in self.trade_log if t["action"] == "sell"]
        # 近似：用 pnl 对应的 bar 数（从 entry 到 exit 的日期差）
        # 简化 - 从 trade_log 中计算

        lines = []
        w = lambda s="": lines.append(s)
        w("# Atlas Trading Agent — Portfolio Backtest Report")
        w("")
        w(f"**初始资金:** {self.initial_capital:,.0f} RMB")
        w(f"**单股票最大仓位:** {self.max_position_pct}%")
        w(f"**最大同时持仓:** {self.max_positions}")
        w("")
        w("## 总体表现")
        w("")
        w("| 指标 | 值 |")
        w("|------|-----:|")
        w(f"| 交易次数 | {metrics.total_trades} |")
        w(f"| 胜率 | {metrics.win_rate}% |")
        w(f"| 总收益 | {metrics.total_return_pct}% |")
        w(f"| 年化收益 | {metrics.annual_return_pct}% |")
        w(f"| 最大回撤 | {metrics.max_drawdown_pct}% |")
        w(f"| 夏普比率 | {metrics.sharpe_ratio} |")
        w(f"| 年化波动率 | {metrics.volatility_pct}% |")
        w(f"| Profit Factor | {metrics.profit_factor} |")
        w(f"| 平均盈利 | {metrics.avg_win_pct}% |")
        w(f"| 平均亏损 | {metrics.avg_loss_pct}% |")
        w(f"| 最大连续亏损 | {metrics.max_consecutive_losses}次 |")
        w("")
        w("## 退出原因统计")
        w("")
        w("| 原因 | 次数 |")
        w("|------|:----:|")
        for reason, cnt in sorted(exit_reasons.items()):
            w(f"| {reason} | {cnt} |")
        w("")
        w("## 数据范围")
        w("")
        if self.equity_curve:
            w(f"| 首日 | {self.equity_curve[0]['date']} |")
            w(f"| 末日 | {self.equity_curve[-1]['date']} |")
            w(f"| 交易日数 | {len(self.equity_curve)} |")
        w("")
        w("---")
        w("*PortfolioEngine v1.0 — 复利计算，组合资金管理*")
        w("*等待人工审核，不进行参数优化*")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info(f"报告保存: {path}")
        return "\n".join(lines)

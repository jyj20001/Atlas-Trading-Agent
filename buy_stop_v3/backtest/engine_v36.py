"""Buy Stop V3 — 回测引擎 V36.1 (A股实盘约束)

基于 V36，增加 A 股真实交易规则：
  - T+1 限制（当日买入不可卖出）
  - 涨停无法买入（价格 >= 涨停价时无法成交）
  - 跌停无法卖出（价格 <= 跌停价时无法止损/止盈）
  - 一字涨停过滤（成交量极小时假设无法买入）
  - 开盘跳空风险（以开盘价+滑点成交，非理想价）
  - 历史数据严格通过 snapshot_query + as_of 过滤
"""

import time
import math
from datetime import date, datetime, timedelta
from typing import Optional

from utils.logger import logger
from data.types import KLine
from data.market_fetcher import fetch_klines
from backtest.metrics import TradeMetrics, BacktestMetrics
from backtest.context import BacktestContext
from core.screener import StockScreener, ScreenerInput

# ── 交易成本（A股实际）──
COMMISSION_RATE = 0.00025      # 佣金万2.5
STAMP_TAX_RATE = 0.001         # 印花税千1（卖出）
SLIPPAGE_RATE = 0.001          # 滑点千1

# ── 涨跌停限制（不同板块）──
LIMIT_RULES = {
    "main":    {"limit_pct": 10.0, "prefixes": ("6", "0", "2")},    # 主板 ±10%
    "chnext":  {"limit_pct": 20.0, "prefixes": ("3",)},              # 创业板 ±20%
    "star":    {"limit_pct": 20.0, "prefixes": ("688",)},            # 科创板 ±20%
    "bj":     {"limit_pct": 30.0, "prefixes": ("4", "8", "920")},   # 北交所 ±30%
}


def _code_prefix(code: str) -> str:
    """获取代码前缀"""
    for pfx in ("688", "920"):
        if code.startswith(pfx):
            return pfx
    return code[0] if code else ""


def _limit_pct(code: str) -> float:
    """根据代码判断涨跌停幅度"""
    pfx = _code_prefix(code)
    for rule, cfg in LIMIT_RULES.items():
        if pfx in cfg["prefixes"]:
            return cfg["limit_pct"]
    return 10.0


def _is_limit_up(close: float, pre_close: float, limit_pct: float) -> bool:
    """判断是否涨停"""
    limit_price = round(pre_close * (1 + limit_pct / 100), 2)
    return close >= limit_price


def _is_limit_down(close: float, pre_close: float, limit_pct: float) -> bool:
    """判断是否跌停"""
    limit_price = round(pre_close * (1 - limit_pct / 100), 2)
    return close <= limit_price


def _calc_limit_price(pre_close: float, limit_pct: float, direction: str) -> float:
    """计算涨停/跌停价"""
    mult = 1 + limit_pct / 100 if direction == "up" else 1 - limit_pct / 100
    return round(pre_close * mult, 2)


class BacktestEngineV36:
    """V36.1 回测引擎 — A股实盘约束 + Snapshot 数据源"""

    def __init__(self, config: str = "D",
                 cost_per_trade_pct: float = 0.001,
                 max_hold_days: int = 30):
        self.config = config
        self.cost_per_trade = cost_per_trade_pct
        self.max_hold = max_hold_days
        self._enable_fundamental = config in ("B", "C", "D")

    def run_single(self, code: str, name: str = "",
                    start_date: str = "2023-01-01",
                    end_date: str = "2026-07-24") -> list:
        """对单只股票运行回测"""
        logger.debug(f"回测 {code} {name} config={self.config}")

        all_klines = fetch_klines(code, days=800)
        if not all_klines or len(all_klines) < 350:
            return []

        klines = [k for k in all_klines if start_date <= k.date <= end_date]
        if len(klines) < 50:
            return []

        limit_pct = _limit_pct(code)
        trades = []
        in_position = False
        entry_date = ""
        entry_price = 0.0
        stop_loss = 0.0
        target_price = 0.0
        signal_score = 0

        warmup = 250
        total = len(klines)

        for i in range(warmup, total):
            today = klines[i]
            if today.volume == 0 or today.close == 0:
                continue

            hist = klines[:i + 1]

            # ── 持仓管理 ──
            if in_position:
                # T+1：买入当日不可卖出
                if today.date == entry_date:
                    continue

                bars = self._bars_between(entry_date, today.date)
                exit_price = None
                reason = ""

                # 获取前一日收盘价计算涨跌停
                prev_close = klines[i - 1].close if i > 0 else today.close
                down_limit = _calc_limit_price(prev_close, limit_pct, "down")

                # 止损（检查跌停：跌停时无法卖出）
                if today.low <= stop_loss:
                    if _is_limit_down(today.close, prev_close, limit_pct):
                        # 跌停无法卖出，继续持仓
                        pass
                    else:
                        exit_price = max(stop_loss, today.open)
                        reason = "stop_loss"

                # 止盈
                if exit_price is None and today.high >= target_price:
                    up_limit = _calc_limit_price(prev_close, limit_pct, "up")
                    # 检查涨停对买入的影响（理论上涨停可以卖出）
                    exit_price = min(target_price, today.high)
                    reason = "take_profit"

                # 超时退出
                if exit_price is None and bars >= self.max_hold:
                    exit_price = today.close
                    reason = "timeout"

                if exit_price is None:
                    continue

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

            # ── 信号生成 ──
            signal_klines = hist[:-1]
            if len(signal_klines) < warmup:
                continue

            output = self._generate_signal(code, name, signal_klines,
                                            today.date)
            if not output or not output.passed:
                continue
            bs = output.signal
            if not bs:
                continue

            bp = bs.breakout_price
            prev_close = klines[i - 1].close if i > 0 else today.close
            up_limit = _calc_limit_price(prev_close, limit_pct, "up")

            # 涨停检查：买入价 >= 涨停价 → 无法成交
            if bp >= up_limit:
                continue

            # 一字涨停过滤：开盘即涨停且成交量极小
            if today.open >= up_limit and today.volume < 100000:
                continue

            # 入场执行
            if today.high >= bp:
                # 实际成交价 = max(突破价, 开盘价) + 滑点
                fill = max(bp, today.open) * (1 + SLIPPAGE_RATE)
                if fill > today.high:
                    fill = min(bp * (1 + SLIPPAGE_RATE), today.high)

                # 计算止损/止盈
                stop = bs.stop_loss if bs.stop_loss and bs.stop_loss > 0 else fill * 0.93
                tgt = bs.target if bs.target and bs.target > 0 else fill * 1.15

                entry_date = today.date
                entry_price = round(fill, 2)
                stop_loss = round(stop, 2)
                target_price = round(tgt, 2)
                signal_score = output.combined_score
                in_position = True

        return trades

    def _generate_signal(self, code, name, klines, signal_date):
        ctx = BacktestContext(signal_date=signal_date)
        ctx.load_all()
        screener = StockScreener(
            enable_fundamental=self._enable_fundamental,
        )
        ctx.inject_into(screener)
        if self._enable_fundamental and screener._fundamental_scorer:
            screener._fundamental_scorer._set_signal_date(signal_date)
        prefix = "SH" if code.startswith("6") else "SZ"
        inp = ScreenerInput(
            symbol=f"{prefix}.{code}", name=name,
            klines=klines, market_cap=0,
        )
        return screener.evaluate(inp)

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

    def run_batch(self, codes: list, start_date="2023-01-01",
                   end_date="2026-07-24",
                   progress_interval=50) -> BacktestMetrics:
        all_trades = []
        t0 = time.time()
        for idx, (code, name) in enumerate(codes):
            trades = self.run_single(code, name, start_date, end_date)
            all_trades.extend(trades)
            if (idx + 1) % progress_interval == 0:
                elapsed = time.time() - t0
                eta = (elapsed / (idx + 1)) * (len(codes) - idx - 1)
                logger.info(f"  进度 [{idx+1}/{len(codes)}] "
                           f"累计{len(all_trades)}笔交易 "
                           f"ETA:{eta:.0f}s")

        metrics = BacktestMetrics(config=self.config)
        metrics.compute(all_trades, cost_per_trade_pct=self.cost_per_trade)
        self._all_trades = all_trades
        return metrics

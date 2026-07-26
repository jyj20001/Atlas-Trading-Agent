"""Atlas Trading Agent — 信号预生成

为 PortfolioEngine 生成所有候选信号（不执行交易）。
与 engine_v36 使用相同的 Screener + BacktestContext 逻辑。
"""

from datetime import date, datetime
from dataclasses import dataclass
from typing import Optional
import time

from utils.logger import logger
from data.market_fetcher import fetch_klines
from core.screener import StockScreener, ScreenerInput
from backtest.context import BacktestContext


@dataclass
class Signal:
    """候选信号"""
    date: str            # 信号日期 YYYY-MM-DD
    code: str
    name: str
    breakout_price: float
    stop_loss: float
    target: float
    score: int
    stage: str = ""
    volume_ratio: float = 0.0
    prev_close: float = 0.0  # 前一日收盘价（用于涨跌停判断）


def collect_signals(codes: list[tuple[str, str]],
                     start_date: str = "2019-01-01",
                     end_date: str = "2025-12-31",
                     config: str = "D",
                     progress_interval: int = 25) -> list[Signal]:
    """预生成所有候选信号。

    遍历每只股票，使用 StockScreener + BacktestContext 生成信号。
    与 engine_v36 使用完全相同的评估逻辑，但不执行交易。

    返回按日期排序的 Signal 列表。
    """
    all_signals: list[Signal] = []
    enable_fundamental = config in ("B", "C", "D")
    t0 = time.time()

    for idx, (code, name) in enumerate(codes):
        try:
            klines = fetch_klines(code, days=800)
        except Exception as e:
            logger.warning(f"获取 {code} K线失败: {e}")
            continue
        if not klines or len(klines) < 350:
            continue

        klines_range = [k for k in klines if start_date <= k.date <= end_date]
        if len(klines_range) < 50:
            continue

        warmup = 250
        total = len(klines_range)

        for i in range(warmup, total):
            today = klines_range[i]
            if today.volume == 0 or today.close == 0:
                continue

            hist = klines_range[:i + 1]
            signal_klines = hist[:-1]
            if len(signal_klines) < warmup:
                continue

            # ── 使用 Screener + BacktestContext（与 engine_v36 一致）──
            ctx = BacktestContext(signal_date=today.date)
            ctx.load_all()
            screener = StockScreener(enable_fundamental=enable_fundamental)
            ctx.inject_into(screener)
            if enable_fundamental and screener._fundamental_scorer:
                screener._fundamental_scorer._set_signal_date(today.date)

            prefix = "SH" if code.startswith("6") else "SZ"
            inp = ScreenerInput(
                symbol=f"{prefix}.{code}", name=name,
                klines=signal_klines, market_cap=0,
            )
            output = screener.evaluate(inp)

            if not output or not output.passed:
                continue
            bs = output.signal
            if not bs:
                continue

            # 记录信号
            prev_close = klines_range[i - 1].close if i > 0 else today.close
            all_signals.append(Signal(
                date=today.date,
                code=code,
                name=name,
                breakout_price=bs.breakout_price,
                stop_loss=bs.stop_loss if bs.stop_loss and bs.stop_loss > 0 else bs.breakout_price * 0.93,
                target=bs.target if bs.target and bs.target > 0 else bs.breakout_price * 1.15,
                score=output.combined_score,
                stage=output.breakout_stage,
                volume_ratio=bs.volume_ratio,
                prev_close=prev_close,
            ))

        if (idx + 1) % progress_interval == 0:
            elapsed = time.time() - t0
            logger.info(f"  信号预生成 [{idx+1}/{len(codes)}] "
                       f"累计{len(all_signals)}信号 "
                       f"ETA:{elapsed/(idx+1)*(len(codes)-idx-1):.0f}s")

    # 按日期排序
    all_signals.sort(key=lambda s: s.date)
    logger.info(f"信号预生成完成: {len(all_signals)} 条, "
               f"日期范围 {all_signals[0].date if all_signals else 'N/A'} ~ "
               f"{all_signals[-1].date if all_signals else 'N/A'}")
    return all_signals

"""
Buy Stop V3 — 批量扫描引擎（生产版）

- 每只股票独立 try/except，不会因为单只异常中断全流程
- K线获取失败自动重试（最多3次）
- 异常股票跳过，记录到 eliminated 列表
- 进度每100只输出一次
- 全流程异常保护
"""

import time
import traceback
from datetime import date, datetime
from typing import Optional

from config.settings import MIN_LISTING_DAYS
from utils.logger import logger
from data.market_fetcher import fetch_klines
from data.types import StockInfo
from core.screener import StockScreener, ScreenerInput, ScreenerOutput
from scanner.universe import build_stock_pool


# ── 扫描结果条目 ──

class ScanResult:
    """单只股票的扫描结果"""
    def __init__(self, stock: StockInfo, output: ScreenerOutput,
                 elapsed: float = 0, error: str = ""):
        self.stock = stock
        self.output = output
        self.elapsed = elapsed
        self.error = error

    @property
    def combined_score(self) -> int:
        return self.output.combined_score if self.output else 0

    @property
    def recommendation(self) -> str:
        return self.output.recommendation if self.output else "ERROR"

    def to_dict(self) -> dict:
        base = {
            "symbol": self.stock.symbol,
            "code": self.stock.code,
            "name": self.stock.name,
            "recommendation": self.recommendation,
            "combined_score": self.combined_score,
            "elapsed_sec": round(self.elapsed, 2),
        }
        if self.error:
            base["error"] = self.error
        if self.output:
            o = self.output
            base.update({
                "breakout_stage": o.breakout_stage,
                "market_score": o.market_score,
                "market_status": o.market_status,
                "sector_score": o.sector_score,
                "fundamental_score": o.fundamental_score,
                "risk_flags": o.risk_flags,
            })
            if o.signal:
                s = o.signal
                base.update({
                    "price": s.price,
                    "buy_stop_price": s.breakout_price,
                    "stop_loss": s.stop_loss,
                    "target": s.target,
                    "volume_ratio": s.volume_ratio,
                    "change_5d": s.change_5d_pct,
                    "suggestion": s.suggestion,
                })
        return base


# ── 扫描结果汇总 ──

class ScanSummary:
    def __init__(self):
        self.total = 0
        self.skipped = 0
        self.errors = 0
        self.candidates = []
        self.eliminated = []
        self.start_time = 0.0
        self.end_time = 0.0
        self.data_source_warning = ""  # 数据源完整性提示

    @property
    def elapsed(self) -> float:
        return self.end_time - self.start_time

    @property
    def scanned_successfully(self) -> int:
        """成功完成扫描的股票数（未抛出异常）"""
        return self.total - self.errors

    @property
    def data_completeness(self) -> float:
        """数据完整率：成功扫描数 / 总数 (0.0~1.0)"""
        if self.total == 0:
            return 1.0
        return round(self.scanned_successfully / self.total, 4)

    @property
    def error_rate(self) -> float:
        """异常率：错误数 / 总数 (0.0~1.0)"""
        if self.total == 0:
            return 0.0
        return round(self.errors / self.total, 4)

    @property
    def health_status(self) -> str:
        """系统健康状态"""
        if self.total == 0:
            return "UNKNOWN"
        er = self.error_rate
        if er < 0.05:
            return "HEALTHY"
        elif er < 0.20:
            return "DEGRADED"
        else:
            return "UNHEALTHY"

    def sort_candidates(self):
        stage_rank = {"EARLY_BREAKOUT": 0, "TRENDING": 1, "EXTENDED": 2, "CLIMAX": 3}
        self.candidates.sort(key=lambda r: (
            -r.combined_score,
            stage_rank.get(r.output.breakout_stage, 99) if r.output else 99,
            -(r.output.fundamental_score if r.output else 0),
        ))

    def top(self, n: int = 20) -> list[ScanResult]:
        return self.candidates[:n]


# ── 预过滤 ──

def _prefilter(symbol: str, name: str, klines) -> Optional[str]:
    """快速预过滤。返回 None=通过，str=淘汰原因"""
    if not klines or len(klines) < MIN_LISTING_DAYS:
        return f"K线不足{MIN_LISTING_DAYS}天"

    latest = klines[-1]
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    price = latest.close

    # MA200
    if len(closes) >= 200:
        ma200 = sum(closes[-200:]) / 200
        if price <= ma200:
            return f"价格{price:.2f} <= MA200{ma200:.2f}"

    # 距离20日最高
    if len(highs) >= 20:
        high20 = max(highs[-20:])
        dist = (price - high20) / high20 * 100
        if dist < -5:
            return f"距20日高{high20:.2f}过远({dist:.1f}%)"

    # 5日涨幅
    if len(klines) >= 6:
        chg_5d = ((latest.close - klines[-6].close) / klines[-6].close * 100)
        if chg_5d > 30:
            return f"5日涨幅{chg_5d:.1f}% > 30%"

    # 连续涨停预检
    limit_count = 0
    for i in range(min(7, len(klines) - 1)):
        idx = len(klines) - 2 - i
        chg = ((klines[idx].close - klines[idx - 1].close) / klines[idx - 1].close * 100) if idx > 0 else 0
        if chg >= 9.5:
            limit_count += 1
        else:
            break
    if limit_count >= 3:
        return f"连续{limit_count}天涨停"

    return None


# ── K线获取（带重试） ──

def _fetch_with_retry(code: str, days: int = 250, max_retries: int = 3) -> Optional[list]:
    """获取K线，失败自动重试"""
    for attempt in range(1, max_retries + 1):
        try:
            klines = fetch_klines(code, days=days)
            if klines and len(klines) >= MIN_LISTING_DAYS:
                return klines
            if attempt < max_retries:
                time.sleep(1)
        except Exception as e:
            logger.debug(f"获取 {code} K线失败 [尝试{attempt}/{max_retries}]: {e}")
            if attempt < max_retries:
                time.sleep(2)
    return None


# ── 批量扫描器 ──

class BatchRunner:
    """生产级批量扫描器"""

    def __init__(self, enable_fundamental: bool = False, max_stocks: int = 0):
        self.enable_fundamental = enable_fundamental
        self.max_stocks = max_stocks

    def run(self, stocks: list[StockInfo]) -> ScanSummary:
        """对股票列表执行批量扫描，异常隔离，单只失败不影响全流程"""
        summary = ScanSummary()
        summary.start_time = time.time()
        summary.total = len(stocks)

        if self.max_stocks > 0:
            stocks = stocks[:self.max_stocks]

        logger.info(f"开始扫描 {len(stocks)} 只股票 (fundamental={self.enable_fundamental})")

        # 每批创建独立的screener实例（避免状态污染）
        screener = StockScreener(enable_fundamental=self.enable_fundamental)

        for idx, stock in enumerate(stocks):
            t0 = time.time()
            symbol = stock.symbol
            code = stock.code
            name = stock.name

            try:
                # 获取K线（带重试）
                klines = _fetch_with_retry(code, days=250)
                if not klines or len(klines) < 200:
                    summary.skipped += 1
                    if (idx + 1) % 50 == 0:
                        logger.debug(f"  [{idx+1}/{summary.total}] {symbol} K线不足，跳过")
                    continue

                # 预过滤
                reason = _prefilter(symbol, name, klines)
                if reason:
                    summary.skipped += 1
                    continue

                # 构建输入
                inp = ScreenerInput(
                    symbol=symbol, name=name,
                    klines=klines,
                    market_cap=stock.market_cap or 0,
                    sector="",
                )

                # 评估
                output = screener.evaluate(inp)
                elapsed = time.time() - t0
                result = ScanResult(stock, output, elapsed)

                if output.passed:
                    summary.candidates.append(result)
                else:
                    summary.eliminated.append(result)

            except Exception as e:
                elapsed = time.time() - t0
                summary.errors += 1
                err_msg = f"{type(e).__name__}: {str(e)[:80]}"
                result = ScanResult(stock, None, elapsed, error=err_msg)
                summary.eliminated.append(result)
                # 只debug日志，不中断
                logger.debug(f"  [{idx+1}/{summary.total}] {symbol} 异常: {err_msg}")
                continue

            # 进度
            if (idx + 1) % 100 == 0:
                elapsed_sofar = time.time() - summary.start_time
                speed = elapsed_sofar / (idx + 1)
                eta = (summary.total - idx - 1) * speed
                logger.info(f"  进度 [{idx+1}/{summary.total}] "
                           f"候选:{len(summary.candidates)} "
                           f"跳过:{summary.skipped} 错误:{summary.errors} "
                           f"预计剩余:{eta:.0f}秒")

        summary.end_time = time.time()
        summary.sort_candidates()

        logger.info(f"扫描完成: {summary.total}只 -> "
                    f"{len(summary.candidates)}候选 "
                    f"/ {summary.skipped}跳过 "
                    f"/ {summary.errors}错误 "
                    f"/ {summary.elapsed:.1f}秒 "
                    f"/ 健康:{summary.health_status} "
                    f"/ 完整率:{summary.data_completeness*100:.1f}%")

        return summary


# ── 便捷函数 ──

def run_scan(market: str = "A", max_stocks: int = 100,
             enable_fundamental: bool = False) -> ScanSummary:
    """一站式扫描"""
    try:
        stocks = build_stock_pool(market)
        if max_stocks > 0:
            logger.info(f"限制扫描前 {max_stocks} 只")
            stocks = stocks[:max_stocks]
        runner = BatchRunner(enable_fundamental=enable_fundamental)
        return runner.run(stocks)
    except Exception as e:
        logger.error(f"扫描流程异常: {e}")
        traceback.print_exc()
        summary = ScanSummary()
        summary.start_time = time.time()
        summary.end_time = time.time()
        summary.total = 0
        summary.errors = 1
        return summary

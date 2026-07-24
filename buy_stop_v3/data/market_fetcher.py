"""
Buy Stop V3 — 行情数据获取模块

数据源：
  - 日K线：腾讯财经 API (web.ifzq.gtimg.cn) — 稳定 HTTPS
  - 股票列表：新浪财经 API (vip.stock.finance.sina.com.cn)
  - 个股基本信息：腾讯/新浪
"""

import json
import math
import time
import random
from datetime import date, timedelta
from typing import Optional
from dataclasses import dataclass

from utils.logger import logger
from data.types import KLine, StockInfo
from data.http_client import get_json, get_text, HttpError


# ── API 端点 ──

_URL_TENCENT_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_URL_SINA_LIST = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"


# ──────────────────────────────────────────────
# 1. 股票列表获取
# ──────────────────────────────────────────────

def fetch_stock_list(market: str = "A") -> list[StockInfo]:
    """
    获取A股股票列表

    market:
      "A"      — 全市场（沪深北）
      "HS300"  — 沪深300成分股

    返回 StockInfo 列表
    """
    if market == "HS300":
        return _fetch_sina_list("hs300")

    return _fetch_sina_list("hs_a")


def _fetch_sina_list(node: str) -> list[StockInfo]:
    """
    新浪财经获取股票列表
    node: hs_a=全A股, hs300=沪深300
    """
    all_stocks: list[StockInfo] = []
    page = 1
    page_size = 100   # 新浪单页上限100
    max_pages = 50    # 100*50=5000 > 全A股

    while page <= max_pages:
        time.sleep(0.3 + random.random() * 0.3)

        url = (
            f"{_URL_SINA_LIST}"
            f"?page={page}&num={page_size}&sort=symbol&asc=1"
            f"&node={node}&symbol=&_s_r_a=page"
        )

        try:
            result = get_json(url, retries=2)
            # 处理新浪返回格式：{"_list": [...]} 或直接 [...]
            if isinstance(result, list):
                items = result
            elif isinstance(result, dict):
                items = result.get("_list") or result.get("data", {}).get("diff", [])
            else:
                items = None

            if not items:
                break

            for item in items:
                code = str(item.get("code", ""))
                all_stocks.append(StockInfo(
                    symbol=_make_symbol(code),
                    code=code,
                    name=str(item.get("name", "")),
                    exchange=_make_exchange(code),
                ))

            if len(items) < page_size:
                break
            page += 1

        except HttpError as e:
            logger.warning(f"新浪列表 page={page} 失败: {e}")
            break

    logger.info(f"新浪 {node}: {len(all_stocks)} 只")
    return all_stocks


# ──────────────────────────────────────────────
# 2. K线数据获取
# ──────────────────────────────────────────────

def fetch_klines(code: str, days: int = 250,
                 end_date: Optional[str] = None) -> Optional[list[KLine]]:
    """
    从腾讯财经获取个股日K线（前复权）

    参数:
        code: 股票代码
        days: 获取天数（默认250）
        end_date: 不适用（腾讯返回全部）

    返回:
        list[KLine] 或 None
    """
    prefix = _tencent_prefix(code)
    if not prefix:
        logger.error(f"无法确定 {code} 的腾讯前缀")
        return None

    param = f"{prefix}{code},day,,,{days},qfq"

    try:
        data = get_json(_URL_TENCENT_KLINE, {"param": param}, retries=3, timeout=10)
    except HttpError as e:
        logger.error(f"获取 {code} K线失败: {e}")
        return None

    # 解析腾讯返回格式
    stock_key = f"{prefix}{code}"
    stock_data = data.get("data", {}).get(stock_key, {})
    klines_raw = stock_data.get("qfqday") or stock_data.get("day")

    if not klines_raw:
        logger.warning(f"{code} 腾讯K线无数据")
        return None

    klines: list[KLine] = []
    for row in klines_raw:
        if len(row) < 6:
            continue
        # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
        date_str = str(row[0])
        try:
            k = KLine(
                date=date_str,
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=int(float(row[5])),
                amount=0.0,
            )
            klines.append(k)
        except (ValueError, IndexError):
            continue

    logger.debug(f"{code}: 腾讯 {len(klines)} 根K线 ({klines[0].date} ~ {klines[-1].date})")
    return klines


def _tencent_prefix(code: str) -> Optional[str]:
    code = code.strip()
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith(("0", "3", "2")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    return None


# ──────────────────────────────────────────────
# 3. 指标计算
# ──────────────────────────────────────────────

@dataclass
class StockIndicators:
    symbol: str
    name: str
    price: float
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    high20: Optional[float] = None
    high60: Optional[float] = None
    low20: Optional[float] = None
    avg_vol_20: Optional[float] = None
    atr14: Optional[float] = None
    change_5d: Optional[float] = None
    change_10d: Optional[float] = None


def compute_indicators(klines: list[KLine], symbol: str = "",
                        name: str = "") -> Optional[StockIndicators]:
    if len(klines) < 20:
        return None

    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    volumes = [k.volume for k in klines]
    latest = klines[-1]

    def ma(data, period):
        return round(sum(data[-period:]) / period, 2) if len(data) >= period else None

    def highest(data, period):
        return max(data[-period:]) if len(data) >= period else None

    def lowest(data, period):
        return min(data[-period:]) if len(data) >= period else None

    # ATR(14)
    atr14 = None
    if len(klines) >= 15:
        trs = []
        for i in range(-14, 0):
            prev = klines[i - 1].close
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - prev), abs(lows[i] - prev))
            trs.append(tr)
        atr14 = round(sum(trs) / 14, 2)

    change_5d = change_10d = None
    if len(klines) >= 6:
        change_5d = round((latest.close - klines[-6].close) / klines[-6].close * 100, 2)
    if len(klines) >= 11:
        change_10d = round((latest.close - klines[-11].close) / klines[-11].close * 100, 2)

    return StockIndicators(
        symbol=symbol, name=name, price=latest.close,
        ma20=ma(closes, 20),
        ma50=ma(closes, 50),
        ma200=ma(closes, 200),
        high20=highest(highs, 20),
        high60=highest(highs, 60) if len(klines) >= 60 else highest(highs, len(klines)),
        low20=lowest(lows, 20),
        avg_vol_20=round(sum(volumes[-20:]) / 20) if len(volumes) >= 20 else None,
        atr14=atr14, change_5d=change_5d, change_10d=change_10d,
    )


# ──────────────────────────────────────────────
# 4. 转换接口
# ──────────────────────────────────────────────

def to_screener_input(klines: list[KLine],
                       stock_info: StockInfo) -> Optional["ScreenerInput"]:
    from core.screener import ScreenerInput
    if len(klines) < 60:
        logger.warning(f"{stock_info.symbol} K线不足(仅{len(klines)}根)")
        return None
    return ScreenerInput(
        symbol=stock_info.symbol,
        name=stock_info.name,
        klines=klines,
        market_cap=stock_info.market_cap or 0,
        sector="",
    )


# ──────────────────────────────────────────────
# 5. 一站式接口：code → ScreenerInput
# ──────────────────────────────────────────────

def stock_to_screener_input(code: str, days: int = 250,
                              end_date: Optional[str] = None
                              ) -> Optional["ScreenerInput"]:
    klines = fetch_klines(code, days=days)
    if not klines:
        return None

    si = StockInfo(
        symbol=_make_symbol(code),
        code=code,
        name=code,
        exchange=_make_exchange(code),
    )
    return to_screener_input(klines, si)


# ── 辅助 ──

def _make_symbol(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"SH.{code}"
    elif code.startswith(("0", "3", "2")):
        return f"SZ.{code}"
    elif code.startswith(("4", "8")):
        return f"BJ.{code}"
    return code


def _make_exchange(code: str) -> str:
    if code.startswith(("6", "9")):
        return "SSE"
    elif code.startswith(("0", "3", "2")):
        return "SZSE"
    elif code.startswith(("4", "8")):
        return "BJSE"
    return "Other"


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "test"

    if action == "list":
        stocks = fetch_stock_list("A")
        print(f"A股总数: {len(stocks)}")
        for s in stocks[:10]:
            print(f"  {s.symbol} {s.name}")
    elif action == "kline":
        code = sys.argv[2] if len(sys.argv) > 2 else "000977"
        klines = fetch_klines(code, days=120)
        if klines:
            print(f"{code}: {len(klines)} K-lines")
            for k in klines[-5:]:
                print(f"  {k.date} O:{k.open} C:{k.close} H:{k.high} L:{k.low} V:{k.volume}")
            ind = compute_indicators(klines, code, "Test")
            if ind:
                print(f"\nMA200={ind.ma200} MA50={ind.ma50} MA20={ind.ma20}")
                print(f"20日高={ind.high20} ATR14={ind.atr14}")
    elif action == "pipeline":
        code = sys.argv[2] if len(sys.argv) > 2 else "000977"
        inp = stock_to_screener_input(code)
        if inp:
            from core.screener import StockScreener
            output = StockScreener().evaluate(inp)
            print(f"通过: {output.passed} | {output.reason or '无'}")
            if output.signal:
                s = output.signal
                print(f"总分: {s.total_score}/100 | {s.suggestion}")
                print(f"量比: {s.volume_ratio:.2f}x  5日涨幅: {s.change_5d_pct:+.2f}%")

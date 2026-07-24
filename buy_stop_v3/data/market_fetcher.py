"""
Atlas Trading Agent — 行情数据获取模块（生产版 v3.5）

数据流：
  股票代码 → 查询SQLite缓存 → 缓存命中且数据完整 → 直接返回
                             缓存不足或缺失  → 请求API补充
                                              → 保存缓存
                                              → 返回

数据源路由：
  主板/创业板（600/000/300等） → 腾讯主域 (web.ifzq.gtimg.cn) — qfqday前复权
  科创板/北交所（688/4/8等）   → 腾讯备用域 (proxy.finance.qq.com) — day未复权
  WAF拦截/失败               → 自动切换备用域

安全保护：
  - 单API请求间隔 0.3~1.0 秒
  - WAF HTML 页面识别
  - JSON 异常快速退出（不重试无效请求）
  - 3次失败后自动切换数据源

接口不变：
  fetch_stock_list()
  fetch_klines()
  compute_indicators()
  to_screener_input()
  stock_to_screener_input()
"""

import json
import math
import subprocess
import random
import time
from datetime import date, datetime, timedelta
from typing import Optional
from dataclasses import dataclass

from utils.logger import logger
from data.types import KLine, StockInfo
from data.http_client import get_json, get_text, HttpError
from data.database import (
    load_klines, save_klines, get_latest_date, count_klines,
    get_db_stats, KLine_to_dict,
)

# ── API 端点 ──

_URL_TENCENT_MAIN = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_URL_TENCENT_BACKUP = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"
_URL_SINA_LIST = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

# ── 市场分类 ──

_KECHUANG_PREFIX = ("688", "689")  # 科创板
_BEIJING_PREFIX = ("4", "8", "920")  # 北交所
_SH_PREFIX = ("5", "6", "9")  # 沪市主板（5=基金, 6=主板, 9=债券）
_SZ_PREFIX = ("0", "1", "2", "3")  # 深市主板/创业板


# ──────────────────────────────────────────────
# 1. 股票列表获取
# ──────────────────────────────────────────────

def fetch_stock_list(market: str = "A") -> list[StockInfo]:
    """
    获取A股股票列表
    market: "A"=全市场, "HS300"=沪深300
    """
    if market == "HS300":
        return _fetch_sina_list("hs300")
    return _fetch_sina_list("hs_a")


def _fetch_sina_list(node: str) -> list[StockInfo]:
    all_stocks: list[StockInfo] = []
    page = 1
    page_size = 100
    max_pages = 50

    while page <= max_pages:
        time.sleep(0.3 + random.random() * 0.3)
        url = (
            f"{_URL_SINA_LIST}"
            f"?page={page}&num={page_size}&sort=symbol&asc=1"
            f"&node={node}&symbol=&_s_r_a=page"
        )
        try:
            result = get_json(url, retries=2)
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
# 2. K线数据获取（带缓存+多数据源+保护机制）
# ──────────────────────────────────────────────

def fetch_klines(code: str, days: int = 250,
                 end_date: Optional[str] = None,
                 use_cache: bool = True) -> Optional[list[KLine]]:
    """
    获取个股日K线（带数据库缓存和数据源路由）

    参数:
        code: 股票代码
        days: 需要的最少K线数
        end_date: 忽略（API返回最新数据）
        use_cache: 是否启用SQLite缓存（默认启用）

    返回:
        list[KLine] 或 None
    """
    # ── 检查缓存 ──
    if use_cache:
        cached = load_klines(code, limit=days)
        latest_db = get_latest_date(code)
        today_str = date.today().isoformat()

        # 如果缓存足够（≥days根）且包含今日或昨日数据，直接返回
        if len(cached) >= days:
            if latest_db and (latest_db == today_str or
                              latest_db == (date.today() - timedelta(days=1)).isoformat()):
                logger.debug(f"{code}: 缓存命中 ({len(cached)}根, 最新{latest_db})")
                return _dicts_to_klines(cached)

    # ── 选择数据源 ──
    is_kechuang = code.startswith(_KECHUANG_PREFIX)
    is_beijing = code.startswith(_BEIJING_PREFIX)

    if is_kechuang or is_beijing:
        # 科创板/北交所 → 腾讯备用域（主域无复权数据）
        klines = _fetch_tencent_api(code, days, use_backup=True)
        source = "tencent_backup"
    else:
        # 主板/创业板 → 腾讯主域，失败时切备用
        klines = _fetch_tencent_with_fallback(code, days)

    if not klines:
        return None

    # ── 写入缓存 ──
    if use_cache and klines:
        source_label = "tencent_backup" if (is_kechuang or is_beijing) else "tencent_main"
        save_klines(code, klines, source=source_label)

    return klines


def _fetch_tencent_with_fallback(code: str, days: int) -> Optional[list[KLine]]:
    """腾讯主域优先，失败后自动切备用域"""
    # 主域
    klines = _fetch_tencent_api(code, days, use_backup=False)
    if klines:
        return klines

    # 失败 → 切备用
    logger.debug(f"{code}: 主域无数据，切换到备用域")
    time.sleep(0.5 + random.random())
    klines = _fetch_tencent_api(code, days, use_backup=True)
    return klines


def _fetch_tencent_api(code: str, days: int,
                       use_backup: bool = False) -> Optional[list[KLine]]:
    """
    从腾讯 API 获取K线

    参数:
        code: 股票代码
        days: 获取天数
        use_backup: True=备用域(proxy.finance.qq.com), False=主域(web.ifzq.gtimg.cn)
    """
    prefix = _tencent_prefix(code)
    if not prefix:
        return None

    base_url = _URL_TENCENT_BACKUP if use_backup else _URL_TENCENT_MAIN
    param = f"{prefix}{code},day,,,{days},qfq"
    full_url = f"{base_url}?param={param}"
    source_label = "备用" if use_backup else "主域"

    # 请求限速
    time.sleep(0.3 + random.random() * 0.4)

    # 执行curl（直接调用，避免http_client的JSON异常重试）
    raw = _safe_curl(full_url)
    if raw is None:
        return None

    # WAF/非JSON检测
    if not raw.startswith("{"):
        if "<!DOCTYPE" in raw or "<html" in raw or "waf" in raw.lower():
            logger.warning(f"{code} [{source_label}]: WAF拦截")
            return None
        logger.debug(f"{code} [{source_label}]: 非JSON响应({raw[:30]})")
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.debug(f"{code} [{source_label}]: JSON解析失败 {e}")
        return None

    # 解析K线
    stock_key = f"{prefix}{code}"
    stock_data = data.get("data", {}).get(stock_key, {})

    # 主域用qfqday（前复权），备用域可能只有day（未复权）
    klines_raw = stock_data.get("qfqday")
    if not klines_raw:
        klines_raw = stock_data.get("day")

    if not klines_raw:
        return None

    klines: list[KLine] = []
    for row in klines_raw:
        if len(row) < 6:
            continue
        date_str = str(row[0])
        try:
            amount_raw = row[6] if len(row) > 6 else 0
            if isinstance(amount_raw, dict):
                amount_raw = 0
            k = KLine(
                date=date_str,
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=int(float(row[5])),
                amount=float(amount_raw),
            )
            klines.append(k)
        except (ValueError, IndexError):
            continue

    if klines:
        logger.debug(f"{code}: {source_label} {len(klines)}根K线 "
                     f"({klines[0].date} ~ {klines[-1].date})")
    return klines


def _safe_curl(url: str, timeout: int = 10) -> Optional[str]:
    """
    安全执行curl请求，返回原始文本或None
    不抛出异常——让调用者决定如何处理
    """
    try:
        cmd = [
            "curl", "-s", "--max-time", str(timeout),
            "--noproxy", "*",
            "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-H", "Referer: https://quote.eastmoney.com/",
            url,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 5
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        return raw
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None


def _tencent_prefix(code: str) -> Optional[str]:
    code = code.strip()
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith(("0", "3", "2")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    return None


def _dicts_to_klines(dicts: list[dict]) -> list[KLine]:
    """将数据库查询结果（dict列表）转回 KLine 对象列表"""
    klines = []
    for d in dicts:
        klines.append(KLine(
            date=d["date"],
            open=d["open"],
            close=d["close"],
            high=d["high"],
            low=d["low"],
            volume=int(d.get("volume", 0)),
            amount=float(d.get("amount", 0)),
        ))
    return klines


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
        ma20=ma(closes, 20), ma50=ma(closes, 50), ma200=ma(closes, 200),
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


# ──────────────────────────────────────────────
# 5. 缓存统计
# ──────────────────────────────────────────────

def print_cache_stats():
    """输出数据库缓存统计"""
    stats = get_db_stats()
    logger.info(f"行情数据库: {stats['total_codes']}只股票, "
                f"{stats['total_rows']}根K线")
    for c in stats["codes"][:5]:
        logger.info(f"  {c['code']}: {c['count']}根, 最新{c['latest']}")
    if len(stats["codes"]) > 5:
        logger.info(f"  ... 共{len(stats['codes'])}只")


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
        klines = fetch_klines(code, days=120, use_cache=False)
        if klines:
            print(f"{code}: {len(klines)} 根K线")
            for k in klines[-5:]:
                print(f"  {k.date} O:{k.open} C:{k.close} H:{k.high} L:{k.low} V:{k.volume}")
            ind = compute_indicators(klines, code, "Test")
            if ind:
                print(f"\nMA200={ind.ma200} MA50={ind.ma50} MA20={ind.ma20}")
                print(f"20日高={ind.high20} ATR14={ind.atr14}")
        else:
            print(f"{code}: ❌ 获取失败")

    elif action == "cache":
        code = sys.argv[2] if len(sys.argv) > 2 else "000977"
        cached = load_klines(code)
        if cached:
            print(f"{code}: 缓存 {len(cached)} 根K线")
            print(f"  最新交易日: {cached[-1]['date']}")
        else:
            print(f"{code}: 无缓存")

    elif action == "stats":
        print_cache_stats()

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

    elif action == "test_all":
        # 测试所有类型股票
        for code in ["600519", "000001", "300750", "688981"]:
            klines = fetch_klines(code, days=250, use_cache=False)
            if klines:
                print(f"{code}: ✅ {len(klines)}根K线")
            else:
                print(f"{code}: ❌ 获取失败")

    else:
        print("用法: python market_fetcher.py [list|kline|cache|stats|pipeline|test_all]")

"""
Buy Stop V3 — 巨潮资讯数据抓取模块

从巨潮资讯网(http://www.cninfo.com.cn)获取：
  - 业绩预告列表（全文搜索）
  - 业绩快报列表
  - 个股公告查询
  - PDF公告元数据

接口设计：
  search_performance_forecasts(start_date, end_date, page=1)
  search_performance_reports(start_date, end_date, page=1)
  search_stock_announcements(stock_code, keyword, start_date, end_date)
  get_stock_org_id(stock_code)  — 从公告中自动获取orgId
"""

import json
import time
import re
import random
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

import urllib.request
import urllib.error
import http.client

from utils.logger import logger
from utils.helpers import cache_get, cache_set
from config.settings import CNINFO, DATA_DIR
from data.types import PerformanceForecast


# ── HTTP 工具 ──

def _ua() -> str:
    return random.choice(CNINFO["USER_AGENTS"])


def _build_req(url: str, data: Optional[dict] = None, method: str = "POST") -> urllib.request.Request:
    headers = {
        "User-Agent": _ua(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
        "Origin": "http://www.cninfo.com.cn",
    }
    if data and method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        body = urlencode(data, encoding="utf-8").encode("utf-8")
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    return req


def _request(url: str, data: Optional[dict] = None, method: str = "POST",
             retries: int = None) -> Optional[dict]:
    if retries is None:
        retries = CNINFO["MAX_RETRIES"]
    timeout = CNINFO["TIMEOUT"]

    for attempt in range(retries):
        try:
            req = _build_req(url, data, method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except (urllib.error.HTTPError, urllib.error.URLError,
                json.JSONDecodeError, OSError, http.client.IncompleteRead) as e:
            logger.warning(f"请求失败 [attempt {attempt + 1}/{retries}]: {e}")
            if attempt < retries - 1:
                time.sleep(CNINFO["REQUEST_INTERVAL"] * (attempt + 1))
    return None


# ── 核心搜索 ──

def _fulltext_search(searchkey: str, page: int = 1, page_size: int = 20,
                     start_date: str = "", end_date: str = "",
                     stock: str = "") -> Optional[list[dict]]:
    """
    巨潮资讯全文搜索接口
    GET http://www.cninfo.com.cn/new/fulltextSearch/full
    """
    params = {
        "searchkey": searchkey,
        "sdate": start_date,
        "edate": end_date,
        "isfulltext": "false",
        "sortName": "pubdate",
        "sortType": "desc",
        "pageNum": page,
        "pageSize": page_size,
    }
    if stock:
        params["stock"] = stock

    url = f"{CNINFO['BASE_URL']}/fulltextSearch/full?{urlencode(params)}"
    result = _request(url, method="GET")

    if result and result.get("announcements"):
        return result["announcements"]
    if result and result.get("totalAnnouncement", 0) > 0 and not result.get("announcements"):
        logger.warning(f"搜索 '{searchkey}' 返回了 {result['totalAnnouncement']} 条但数据为空")
    return None


def _parse_forecast_from_title(title: str) -> dict:
    """
    从业绩预告标题中尝试提取关键数据。
    如: "浪潮信息：2026年半年度业绩预告" -> {type: "预告"}
    部分详细标题会包含利润信息
    """
    info = {"forecast_type": "", "net_profit_lower": None, "net_profit_upper": None}

    if "业绩预告" in title:
        info["forecast_type"] = "业绩预告"
    elif "业绩快报" in title:
        info["forecast_type"] = "业绩快报"
    elif "业绩报告" in title:
        info["forecast_type"] = "业绩报告"
    elif "业绩预计" in title:
        info["forecast_type"] = "业绩预告"
    else:
        info["forecast_type"] = "其他"

    # 尝试提取利润数字: 净利润 xxx 万元 ~ xxx 万元
    profit_pattern = r"(?:净利润|归属于上市公司股东的净利润)[：:\s]*约?([\d,.-]+)[~-]([\d,.-]+)\s*万"
    m = re.search(profit_pattern, title)
    if m:
        info["net_profit_lower"] = float(m.group(1).replace(",", ""))
        info["net_profit_upper"] = float(m.group(2).replace(",", ""))

    # 尝试提取变动幅度: 增长/下降 xxx% ~ xxx%
    change_pattern = r"(?:增长|上升|下降|减少)[：:\s]*([\d.]+)%[~-]([\d.]+)%"
    m = re.search(change_pattern, title)
    if m:
        info["change_pct_lower"] = float(m.group(1))
        info["change_pct_upper"] = float(m.group(2))

    return info


def search_performance_forecasts(start_date: Optional[str] = None,
                                  end_date: Optional[str] = None,
                                  page: int = 1,
                                  page_size: int = 30) -> list[PerformanceForecast]:
    """
    搜索业绩预告
    返回 PerformanceForecast 列表
    """
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    logger.info(f"搜索业绩预告: {start_date} ~ {end_date}, page={page}")

    items = _fulltext_search(
        searchkey="业绩预告",
        page=page,
        page_size=min(page_size, 15),  # 巨潮返回较大结果时可能截断，限制单页大小
        start_date=start_date,
        end_date=end_date,
    )

    if not items:
        logger.info("无业绩预告结果")
        return []

    results: list[PerformanceForecast] = []
    for item in items:
        title = item.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
        date_ts = item.get("announcementTime", 0)
        announce_date = ""
        if date_ts:
            announce_date = date.fromtimestamp(date_ts / 1000).isoformat()

        parsed = _parse_forecast_from_title(title)

        pf = PerformanceForecast(
            code=item.get("secCode", ""),
            name=item.get("secName", ""),
            announce_date=announce_date,
            report_type=parsed.get("forecast_type", "业绩预告"),
            forecast_type="业绩预告",
            net_profit_lower=parsed.get("net_profit_lower"),
            net_profit_upper=parsed.get("net_profit_upper"),
            change_pct_lower=parsed.get("change_pct_lower"),
            change_pct_upper=parsed.get("change_pct_upper"),
        )
        results.append(pf)

    logger.info(f"获取到 {len(results)} 条业绩预告")
    return results


def search_performance_reports(start_date: Optional[str] = None,
                                end_date: Optional[str] = None,
                                page: int = 1,
                                page_size: int = 30) -> list[PerformanceForecast]:
    """
    搜索业绩快报
    """
    if not start_date:
        start_date = (date.today() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    logger.info(f"搜索业绩快报: {start_date} ~ {end_date}, page={page}")

    items = _fulltext_search(
        searchkey="业绩快报",
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
    )

    if not items:
        logger.info("无业绩快报结果")
        return []

    results: list[PerformanceForecast] = []
    for item in items:
        title = item.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
        date_ts = item.get("announcementTime", 0)
        announce_date = ""
        if date_ts:
            announce_date = date.fromtimestamp(date_ts / 1000).isoformat()

        parsed = _parse_forecast_from_title(title)

        pf = PerformanceForecast(
            code=item.get("secCode", ""),
            name=item.get("secName", ""),
            announce_date=announce_date,
            report_type=parsed.get("forecast_type", "业绩快报"),
            forecast_type="业绩快报",
        )
        results.append(pf)

    logger.info(f"获取到 {len(results)} 条业绩快报")
    return results


def search_stock_announcements(stock_code: str,
                                keyword: str = "",
                                start_date: Optional[str] = None,
                                end_date: Optional[str] = None,
                                page: int = 1) -> list[dict]:
    """
    搜索某只股票的公告
    """
    if not start_date:
        start_date = (date.today() - timedelta(days=90)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    searchkey = f"{keyword} {stock_code}" if keyword else stock_code
    logger.info(f"搜索个股公告: {stock_code} keyword='{keyword}'")

    items = _fulltext_search(
        searchkey=searchkey,
        page=page,
        page_size=20,
        start_date=start_date,
        end_date=end_date,
    )

    if not items:
        return []

    result_list = []
    for item in items:
        title = item.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
        date_ts = item.get("announcementTime", 0)
        announce_date = ""
        if date_ts:
            announce_date = date.fromtimestamp(date_ts / 1000).isoformat()

        result_list.append({
            "code": item.get("secCode", ""),
            "name": item.get("secName", ""),
            "title": title,
            "date": announce_date,
            "org_id": item.get("orgId", ""),
            "pdf_url": f"{CNINFO['BASE_URL']}/{item.get('adjunctUrl', '')}" if item.get("adjunctUrl") else "",
        })

    return result_list


def get_stock_org_id(stock_code: str) -> Optional[str]:
    """
    通过查询公告自动获取股票的 orgId
    """
    # 尝试从缓存读取
    cached = cache_get("org_id", stock_code, ttl_seconds=86400)
    if cached:
        return cached

    items = _fulltext_search(
        searchkey=stock_code,
        page=1,
        page_size=1,
    )
    if items and len(items) > 0:
        org_id = items[0].get("orgId", "")
        if org_id:
            cache_set("org_id", stock_code, data=org_id)
            return org_id

    logger.warning(f"无法获取 {stock_code} 的 orgId")
    return None


# ── 如果直接运行，做演示测试 ──

if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "forecast"

    if action == "forecast":
        results = search_performance_forecasts(
            start_date="2026-07-20", end_date="2026-07-24"
        )
        for r in results[:10]:
            print(f"  [{r.announce_date}] {r.code} {r.name}: {r.report_type}")

    elif action == "report":
        results = search_performance_reports(
            start_date="2026-07-20", end_date="2026-07-24"
        )
        for r in results[:10]:
            print(f"  [{r.announce_date}] {r.code} {r.name}: {r.forecast_type}")

    elif action == "stock":
        code = sys.argv[2] if len(sys.argv) > 2 else "000977"
        results = search_stock_announcements(code, keyword="业绩预告")
        for r in results[:5]:
            print(f"  [{r['date']}] {r['code']} {r['name']}: {r['title'][:50]}")
            if r['pdf_url']:
                print(f"       PDF: {r['pdf_url']}")

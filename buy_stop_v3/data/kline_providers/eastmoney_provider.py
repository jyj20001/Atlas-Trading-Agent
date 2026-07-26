"""Atlas Trading Agent — 东方财富 K线 Provider

HTTP API: push2his.eastmoney.com
无登录/Token 要求，免费使用。

前复权: fqt=1
历史长度: 上市首日至今
性能: ~500ms 每只（含限速）
"""

import json
import os
import time
from typing import Optional
from urllib.request import urlopen, Request

from .base import KLineProvider, KLineNormalized


EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# secid 映射: SH=1, SZ=0
_MARKET_MAP = {
    "6": 1, "9": 1,      # 沪市
    "0": 0, "3": 0, "2": 0,  # 深市
}


def _secid(code: str) -> str:
    """将 A 股代码转为东方财富 secid 格式"""
    prefix = code[0]
    market = _MARKET_MAP.get(prefix, 1)
    return f"{market}.{code}"


_ADJUST_MAP = {"qfq": 1, "hfq": 2, "none": 0}


class EastMoneyProvider(KLineProvider):

    @property
    def name(self) -> str:
        return "eastmoney"

    @property
    def priority(self) -> int:
        return 0  # 最高优先级

    def fetch(self, code: str, *,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              adjust: str = "qfq",
              max_count: int = 2000) -> list[KLineNormalized]:
        fqt = _ADJUST_MAP.get(adjust, 1)

        params = (
            f"secid={_secid(code)}"
            f"&fields1=f1,f2,f3,f4,f5,f6"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101"           # 日K
            f"&fqt={fqt}"         # 复权
            f"&lmt={max_count}"
            f"&end=20500101"
        )
        url = f"{EASTMONEY_URL}?{params}"

        # 限速 + 重试
        for attempt in range(2):
            time.sleep(1.0)
            req = Request(url, headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            try:
                with urlopen(req, timeout=5) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                break
            except Exception:
                if attempt == 1:
                    return []
                continue

        data = raw.get("data") if isinstance(raw, dict) else None
        if not data:
            return []

        klines_raw = data.get("klines")
        if not klines_raw:
            return []

        results: list[KLineNormalized] = []
        for line in klines_raw:
            fields = line.split(",")
            if len(fields) < 11:
                continue
            try:
                trade_date = fields[0].strip()  # "2026-07-24"
                open_p = float(fields[1])
                close = float(fields[2])
                high = float(fields[3])
                low = float(fields[4])
                volume = int(float(fields[5]))
                amount = float(fields[6])
            except (ValueError, IndexError):
                continue

            # 过滤 start/end
            if start_date and trade_date < start_date:
                continue
            if end_date and trade_date > end_date:
                continue

            results.append(KLineNormalized(
                code=code,
                trade_date=trade_date,
                open=open_p, high=high, low=low, close=close,
                volume=volume, amount=amount,
                source="eastmoney",
                adjust_type=adjust,
            ))

        # 按日期升序
        results.sort(key=lambda k: k.trade_date)
        return results

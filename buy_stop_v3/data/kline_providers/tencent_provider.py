"""Atlas Trading Agent — 腾讯 K线 Provider (Fallback)

封装现有 market_fetcher._fetch_tencent_api 逻辑。
按统一接口输出 KLineNormalized。
"""

import json
import os
import random
import subprocess
import time
from typing import Optional

from .base import KLineProvider, KLineNormalized


TENCENT_MAIN = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_BACKUP = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get"


def _prefix(code: str) -> Optional[str]:
    code = code.strip()
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith(("0", "3", "2")):
        return "sz"
    elif code.startswith(("4", "8")):
        return "bj"
    return None


_ADJUST_PARAM = {"qfq": "qfq", "hfq": "hfq", "none": ""}


class TencentProvider(KLineProvider):

    @property
    def name(self) -> str:
        return "tencent"

    @property
    def priority(self) -> int:
        return 1  # 低于 eastmoney

    def fetch(self, code: str, *,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              adjust: str = "qfq",
              max_count: int = 2000) -> list[KLineNormalized]:
        adj_param = _ADJUST_PARAM.get(adjust, "qfq")
        prefix = _prefix(code)
        if not prefix:
            return []

        # 先从主域获取，失败切备用
        klines = self._fetch_one(code, prefix, max_count, adj_param,
                                 use_backup=False)
        if not klines:
            time.sleep(0.5 + random.random())
            klines = self._fetch_one(code, prefix, max_count, adj_param,
                                     use_backup=True)

        if not klines:
            return []

        results = []
        for row in klines:
            if len(row) < 6:
                continue
            date_str = str(row[0])
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue
            try:
                amount_raw = row[6] if len(row) > 6 else 0
                if not isinstance(amount_raw, (int, float)):
                    amount_raw = 0
                results.append(KLineNormalized(
                    code=code,
                    trade_date=date_str,
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=int(float(row[5])),
                    amount=float(amount_raw),
                    source="tencent",
                    adjust_type=adjust,
                ))
            except (ValueError, IndexError):
                continue

        results.sort(key=lambda k: k.trade_date)
        return results

    def _fetch_one(self, code: str, prefix: str, days: int,
                    adj_param: str, use_backup: bool) -> Optional[list]:
        """单次请求腾讯 API"""
        base_url = TENCENT_BACKUP if use_backup else TENCENT_MAIN
        adj_suffix = f",{adj_param}" if adj_param else ""
        param = f"{prefix}{code},day,,,{days}{adj_suffix}"
        url = f"{base_url}?param={param}"

        time.sleep(0.3 + random.random() * 0.4)

        try:
            cmd = [
                "curl", "-s", "--max-time", "10",
                "--connect-timeout", "5",
                "--noproxy", "*",
                "-H", ("User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36"),
                "-H", "Referer: https://web.ifzq.gtimg.cn/",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=15)
            if result.returncode != 0:
                return None
            raw = result.stdout.strip()
            if not raw or not raw.startswith("{"):
                return None
        except Exception:
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        stock_key = f"{prefix}{code}"
        stock_data = (data.get("data", {}).get(stock_key, {}))

        # qfqday（前复权）→ day（未复权/后复权）
        raw_rows = stock_data.get("qfqday") or stock_data.get("day")
        if not raw_rows:
            return None

        return raw_rows

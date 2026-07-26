"""Atlas Trading Agent — K线数据标准化器

将 Provider 输出的 KLineNormalized 转为:
1. KLine 对象（与现有系统兼容）
2. dict（用于 DB 写入）
"""

from typing import Optional
from .kline_providers.base import KLineNormalized
from .types import KLine


def normalized_to_kline(nk: KLineNormalized) -> KLine:
    """KLineNormalized → KLine（兼容现有系统）"""
    return KLine(
        date=nk.trade_date,
        open=nk.open,
        close=nk.close,
        high=nk.high,
        low=nk.low,
        volume=nk.volume,
        amount=nk.amount,
    )


def normalized_to_dict(nk: KLineNormalized) -> dict:
    """KLineNormalized → dict（用于 DB 写入）"""
    return {
        "code": nk.code,
        "trade_date": nk.trade_date,
        "open": nk.open,
        "high": nk.high,
        "low": nk.low,
        "close": nk.close,
        "volume": float(nk.volume),
        "amount": nk.amount,
        "source": nk.source,
        "adjust_type": nk.adjust_type,
    }


def merge_and_dedup(existing: list[dict], new_items: list[KLineNormalized]
                    ) -> list[dict]:
    """合并新旧数据，按 trade_date 去重"""
    def _normalize_key(d):
        """将 'date' 转为 'trade_date'"""
        if "date" in d and "trade_date" not in d:
            d["trade_date"] = d.pop("date")
        return d.get("trade_date") or d.get("date") or ""
    date_map = {_normalize_key(d): d for d in existing}
    for nk in new_items:
        date_map[nk.trade_date] = normalized_to_dict(nk)
    return sorted(date_map.values(),
                  key=lambda d: d.get("trade_date") or d.get("date", ""))

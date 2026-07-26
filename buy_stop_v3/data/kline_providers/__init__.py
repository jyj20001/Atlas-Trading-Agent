"""Atlas Trading Agent — K线 Provider 链

Provider 按优先级排列，fetch_klines 依次尝试。
"""

from .base import KLineProvider, KLineNormalized
from .eastmoney_provider import EastMoneyProvider
from .tencent_provider import TencentProvider


# ── Provider 链（按优先级排序）──
_PROVIDERS: list[KLineProvider] = [
    EastMoneyProvider(),   # priority=0: 东方财富
    TencentProvider(),     # priority=1: 腾讯 fallback
]

# 条件导入 FutuProvider（仅当 OpenD 可用时激活）
try:
    from .futu_provider import FutuProvider
    # 插入到最前面（priority=-1 最高）
    _PROVIDERS.insert(0, FutuProvider())
except ImportError:
    pass


def get_providers() -> list[KLineProvider]:
    """返回 Provider 列表（已排序）"""
    return sorted(_PROVIDERS, key=lambda p: p.priority)


def fetch_from_chain(code: str, *,
                     start_date: str = "",
                     end_date: str = "",
                     adjust: str = "qfq",
                     max_count: int = 2000,
                     min_bars: int = 200) -> list[KLineNormalized]:
    """通过 Provider 链获取 K 线（自动 fallback）

    按优先级依次尝试，直到获取足够的数据。
    """
    for provider in get_providers():
        try:
            klines = provider.fetch(
                code,
                start_date=start_date or None,
                end_date=end_date or None,
                adjust=adjust,
                max_count=max_count,
            )
            if klines and len(klines) >= min_bars:
                return klines
            if klines:
                # 数据不足 min_bars 但也返回一些
                pass
        except Exception:
            continue

    return []

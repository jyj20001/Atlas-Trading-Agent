"""Atlas Trading Agent — K线数据源Provider基类"""

from abc import ABC, abstractmethod
from typing import Optional, Protocol
from dataclasses import dataclass


@dataclass
class KLineNormalized:
    """统一K线输出格式"""
    code: str
    trade_date: str          # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int              # 股
    amount: float            # 成交额(元)
    source: str = "tencent"  # 数据源标识
    adjust_type: str = "qfq" # 复权类型: qfq/hfq/none


class KLineProvider(ABC):
    """K线数据源抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源唯一标识"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级: 0=最高, 越大越低"""
        ...

    @abstractmethod
    def fetch(self, code: str, *,
              start_date: Optional[str] = None,
              end_date: Optional[str] = None,
              adjust: str = "qfq",
              max_count: int = 2000) -> list[KLineNormalized]:
        """获取历史日K线

        Args:
            code: A股代码 (如 "600000")
            start_date: 开始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD
            adjust: 复权类型 qfq/hfq/none
            max_count: 最大返回数量

        Returns:
            list[KLineNormalized] 按日期升序排列
        """
        ...

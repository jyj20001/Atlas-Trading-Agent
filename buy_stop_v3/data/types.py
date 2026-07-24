"""
Buy Stop V3 — 数据类型的定义
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


@dataclass
class KLine:
    """单根K线"""
    date: str            # "2026-07-24"
    open: float
    close: float
    high: float
    low: float
    volume: int          # 股
    amount: float        # 成交额(元)
    pre_close: Optional[float] = None
    change_pct: Optional[float] = None  # 涨跌幅%


@dataclass
class StockInfo:
    """股票基本信息"""
    symbol: str          # "SZ.000977"
    code: str            # "000977"
    name: str            # "浪潮信息"
    exchange: str        # "SZSE"
    market_cap: Optional[float] = None    # 流通市值(元)
    total_shares: Optional[float] = None  # 总股本


@dataclass
class BreakoutSignal:
    """突破信号"""
    symbol: str
    name: str
    price: float                    # 当前价
    breakout_price: float           # 突破参考价(20日高/平台位)
    ma200: Optional[float]          # MA200
    above_ma200: bool
    volume_ratio: float             # 量比
    turnover_pct: Optional[float]   # 换手率%
    change_5d_pct: float           # 5日涨幅%
    consecutive_limit: int          # 连续涨停天数
    days_since_breakout: int        # 突破20日高后经过的天数

    # 评分
    score_trend: float = 0
    score_structure: float = 0
    score_volume: float = 0
    score_turnover: float = 0
    score_sector: float = 0
    score_risk: float = 0
    total_score: float = 0

    # 建议
    suggestion: str = "观望"
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    risk_reward: Optional[float] = None


@dataclass
class PerformanceForecast:
    """巨潮资讯——业绩预告/快报"""
    code: str
    name: str
    announce_date: str          # 公告日期
    report_type: str            # 预告类型(预增/预减/首亏等)
    forecast_type: str          # "业绩预告" / "业绩快报"
    net_profit_lower: Optional[float] = None   # 净利润下限(万元)
    net_profit_upper: Optional[float] = None   # 净利润上限(万元)
    change_pct_lower: Optional[float] = None   # 变动下限%
    change_pct_upper: Optional[float] = None   # 变动上限%

    @property
    def profit_change_pct(self) -> Optional[float]:
        """估算变动中值"""
        if self.change_pct_lower is not None and self.change_pct_upper is not None:
            return (self.change_pct_lower + self.change_pct_upper) / 2
        return None


@dataclass
class ScreenerResult:
    """扫描结果"""
    scan_date: str
    total_stocks: int
    candidates: list[BreakoutSignal] = field(default_factory=list)
    eliminated: list[dict] = field(default_factory=list)
    market_summary: dict = field(default_factory=dict)

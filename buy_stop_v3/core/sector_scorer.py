"""
Buy Stop V3 — 板块强度评分模块

计算个股相对所在板块的超额收益。
板块数据来源：腾讯财经行业指数。

评分规则（0~10分）：
  stock_return - sector_return >= 5%  → +10
  >= 3%                                → +8
  >= 1%                                → +5
  0附近 (-1%~1%)                      → +2
  负超额                                → +0
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from utils.logger import logger
from data.http_client import get_json


# ── 板块代码映射（腾讯行业指数） ──

# 常用板块及其腾讯指数代码
SECTOR_INDEX_MAP = {
    # 行业
    "半导体": "sz980017",
    "芯片": "sz980017",
    "人工智能": "sz980021",
    "AI": "sz980021",
    "计算机": "sz980022",
    "通信": "sz980024",
    "5G": "sz980024",
    "电子": "sz980014",
    "消费电子": "sz980014",
    "新能源汽车": "sz980054",
    "新能源车": "sz980054",
    "新能源": "sz980050",
    "汽车": "sz980054",
    "医药": "sz980036",
    "医疗": "sz980036",
    "创新药": "sz980037",
    "生物医药": "sz980038",
    "食品饮料": "sz980060",
    "白酒": "sz980062",
    "消费": "sz980060",
    "家电": "sz980064",
    "房地产": "sz980070",
    "银行": "sz980080",
    "券商": "sz980082",
    "证券": "sz980082",
    "保险": "sz980084",
    "军工": "sz980090",
    "国防": "sz980090",
    "机械": "sz980100",
    "化工": "sz980110",
    "有色": "sz980120",
    "钢铁": "sz980130",
    "煤炭": "sz980140",
    "电力": "sz980150",
    "公用事业": "sz980150",
    "交通运输": "sz980160",
    "建筑": "sz980170",
    "建材": "sz980180",
    "农业": "sz980190",
    "传媒": "sz980200",
    "互联网": "sz980022",
    "游戏": "sz980200",
    # 宽基备用
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "创业板": "sz399006",
}


@dataclass
class SectorScore:
    """板块强度评分"""
    score: int                # 0~10
    sector_name: str          # 板块名称
    sector_return_5d: float   # 板块5日涨幅%
    stock_return_5d: float    # 个股5日涨幅%
    excess_return: float      # 超额收益%
    description: str = ""


# ──────────────────────────────────────────────
# 核心评分器
# ──────────────────────────────────────────────

class SectorScorer:
    """
    板块强度评分器

    输入个股代码和行业名称，计算个股相对板块的超额收益。
    """

    def __init__(self):
        self._index_cache = {}

    # ── 主入口 ──

    def evaluate(self, stock_code: str, sector: str,
                  stock_klines: list) -> SectorScore:
        """
        评估个股的板块强度

        参数:
            stock_code: 股票代码
            sector: 板块/行业名称
            stock_klines: 个股K线（用于计算5日涨幅）

        返回:
            SectorScore
        """
        # 1. 获取板块指数代码
        index_code = self._resolve_sector_index(sector)
        if not index_code:
            return SectorScore(
                score=2, sector_name=sector or "未知",
                sector_return_5d=0, stock_return_5d=0, excess_return=0,
                description="板块无法识别，给默认分",
            )

        # 2. 获取板块指数K线 + 个股5日涨幅
        sector_return = self._get_index_return(index_code)
        stock_return = self._stock_return_5d(stock_klines)

        excess = stock_return - sector_return

        # 3. 评分
        if excess >= 5:
            score = 10
            desc = "独立于板块的强势"
        elif excess >= 3:
            score = 8
            desc = "明显强于板块"
        elif excess >= 1:
            score = 5
            desc = "略强于板块"
        elif excess >= -1:
            score = 2
            desc = "跟随板块走势"
        else:
            score = 0
            desc = "弱于板块"

        return SectorScore(
            score=score,
            sector_name=sector,
            sector_return_5d=round(sector_return, 2),
            stock_return_5d=round(stock_return, 2),
            excess_return=round(excess, 2),
            description=desc,
        )

    # ── 板块指数查询 ──

    def _resolve_sector_index(self, sector: str) -> Optional[str]:
        """根据行业名称匹配板块指数代码"""
        if not sector:
            return None
        # 精确匹配
        if sector in SECTOR_INDEX_MAP:
            return SECTOR_INDEX_MAP[sector]
        # 模糊匹配
        for keyword, index_code in SECTOR_INDEX_MAP.items():
            if keyword in sector or sector in keyword:
                return index_code
        return None

    def _get_index_return(self, index_code: str) -> float:
        """获取板块指数5日涨幅"""
        if index_code in self._index_cache:
            return self._index_cache[index_code]

        try:
            # 腾讯财经API取板块指数日线
            data = get_json(
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                {"param": f"{index_code},day,,,10,qfq"},
                retries=2
            )
            # 解析
            stock_data = data.get("data", {})
            # 尝试多种key
            key = None
            for k in stock_data:
                if k != "qt":
                    key = k
                    break
            if not key:
                return 0.0

            raw = (stock_data[key].get("qfqday") or stock_data[key].get("day") or [])
            if len(raw) < 6:
                return 0.0

            close_now = float(raw[-1][2]) if len(raw[-1]) > 2 else 0
            close_5d = float(raw[-6][2]) if len(raw[-6]) > 2 else close_now
            ret = (close_now - close_5d) / close_5d * 100 if close_5d > 0 else 0

            self._index_cache[index_code] = ret
            return ret

        except Exception as e:
            logger.debug(f"获取板块指数 {index_code} 失败: {e}")
            return 0.0

    @staticmethod
    def _stock_return_5d(klines: list) -> float:
        if not klines or len(klines) < 6:
            return 0.0
        def _get_close(k):
            if hasattr(k, 'close'):
                return k.close
            if isinstance(k, dict):
                return k.get('close', 0)
            if isinstance(k, (list, tuple)):
                return float(k[2])
            return float(k)
        close_now = _get_close(klines[-1])
        close_5d = _get_close(klines[-6])
        return (close_now - close_5d) / close_5d * 100 if close_5d > 0 else 0.0

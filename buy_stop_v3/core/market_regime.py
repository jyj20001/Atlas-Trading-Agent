"""
Buy Stop V3 — 市场环境评分模块

通过三大指数（沪深300、上证指数、创业板）判断当前市场状态。
输入指数K线，输出 MarketRegime（趋势评分 + 市场状态）。

评分规则（0~5分）：
  沪深300(主要权重)  +  上证(辅助)  +  创业板(情绪)
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from utils.logger import logger


# ── 指数代码映射 ──

INDEX_CODES = {
    "沪深300": "000300",
    "上证指数": "000001",
    "创业板指": "399006",
}

INDEX_TENCENT_PREFIX = {
    "000300": "sh",
    "000001": "sh",
    "399006": "sz",
}


@dataclass
class MarketRegime:
    """市场环境评估结果"""
    trend_score: int              # 0~5
    market_status: str            # bull / neutral / bear
    hs300_trend: str = ""         # 沪深300趋势描述
    sh_trend: str = ""            # 上证趋势描述
    cyb_trend: str = ""           # 创业板趋势描述
    hs300_change_5d: float = 0.0
    rising_ratio: Optional[float] = None  # 上涨股票比例（如有全市场数据）


# ──────────────────────────────────────────────
# 核心评分器
# ──────────────────────────────────────────────

class MarketRegimeScorer:
    """
    市场环境评分器

    使用腾讯财经API获取三大指数K线，评估市场状态。
    """

    def __init__(self):
        self._cache = {}  # 缓存原始K线避免重复请求

    # ── 主入口 ──

    def evaluate(self, hs300_klines: list,
                  sh_klines: list,
                  cyb_klines: list) -> MarketRegime:
        """
        对三大指数K线进行市场环境评估

        参数:
            hs300_klines: 沪深300日K线（最新最后）
            sh_klines: 上证指数日K线
            cyb_klines: 创业板指日K线

        返回:
            MarketRegime
        """
        hs300_score = self._score_single(hs300_klines)
        sh_score = self._score_single(sh_klines)
        cyb_score = self._score_single(cyb_klines)

        # 加权综合：沪深300权重0.5 + 上证0.25 + 创业板0.25
        weighted = round(hs300_score * 0.5 + sh_score * 0.25 + cyb_score * 0.25)

        # 市场状态
        if weighted >= 4:
            status = "bull"
        elif weighted >= 2:
            status = "neutral"
        else:
            status = "bear"

        return MarketRegime(
            trend_score=weighted,
            market_status=status,
            hs300_trend=self._describe(hs300_klines, hs300_score),
            sh_trend=self._describe(sh_klines, sh_score),
            cyb_trend=self._describe(cyb_klines, cyb_score),
            hs300_change_5d=self._change_5d(hs300_klines),
        )

    # ── 单指数评分 ──

    def _score_single(self, klines: list) -> int:
        """对单个指数K线评分 0~5"""
        if not klines or len(klines) < 20:
            return 0

        # 兼容KLine对象/dict/tuple多种格式
        def _get_price(k, key_or_idx):
            if hasattr(k, key_or_idx):
                return getattr(k, key_or_idx)
            if isinstance(k, dict):
                return k.get(key_or_idx if isinstance(key_or_idx, str) else str(key_or_idx),
                             k.get('close', 0))
            if isinstance(k, (list, tuple)):
                idx = 2 if key_or_idx == 'close' else (
                    3 if key_or_idx == 'high' else 4)
                return float(k[idx])
            return float(k)

        closes = [_get_price(k, 'close') for k in klines]
        highs = [_get_price(k, 'high') for k in klines]
        latest_price = closes[-1]
        ma20 = sum(closes[-20:]) / 20

        score = 0

        # 价格 > MA20
        if latest_price > ma20:
            score += 3
            # MA20方向
            ma20_prev = sum(closes[-21:-1]) / 20
            if ma20 > ma20_prev:
                score += 2  # MA20向上，再+2
        else:
            score += 0  # 跌破MA20

        # 5日涨跌加分
        chg5 = self._change_5d(klines)
        if chg5 > 3:
            score = min(5, score + 1)
        elif chg5 < -3:
            score = max(0, score - 1)

        return max(0, min(5, score))

    # ── 辅助 ──

    @staticmethod
    def _change_5d(klines: list) -> float:
        if len(klines) < 6:
            return 0.0
        k_last = klines[-1]
        k_5d = klines[-6]
        if hasattr(k_last, 'close'):
            return (k_last.close - k_5d.close) / k_5d.close * 100
        if isinstance(k_last, dict):
            return (k_last['close'] - k_5d['close']) / k_5d['close'] * 100
        if isinstance(k_last, (list, tuple)):
            return (float(k_last[2]) - float(k_5d[2])) / float(k_5d[2]) * 100
        return 0.0

    @staticmethod
    def _describe(klines: list, score: int) -> str:
        if score >= 4:
            return "强势上涨"
        elif score >= 2:
            return "窄幅震荡"
        else:
            return "弱势下行"

    # ── 从市场获取指数K线 ──

    @staticmethod
    def fetch_index_klines(code: str, days: int = 60) -> Optional[list]:
        """
        从腾讯财经获取指数K线
        用于外部调用：从 market_fetcher 获取不到指数，需要用腾讯API直取
        """
        from data.http_client import get_json

        prefix = INDEX_TENCENT_PREFIX.get(code, "sh")
        param = f"{prefix}{code},day,,,{days},qfq"

        try:
            data = get_json(
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                {"param": param}, retries=2
            )
            stock_key = f"{prefix}{code}"
            raw = (data.get("data", {}).get(stock_key, {})
                   .get("qfqday") or data.get("data", {}).get(stock_key, {}).get("day"))
            if not raw:
                return None
            # 统一为 KLine 格式（but we just use tuples）
            result = []
            for row in raw:
                if len(row) >= 6:
                    result.append({
                        "date": row[0], "open": float(row[1]),
                        "close": float(row[2]), "high": float(row[3]),
                        "low": float(row[4]), "volume": int(float(row[5])),
                    })
            return result
        except Exception as e:
            logger.debug(f"获取指数K线 {code} 失败: {e}")
            return None


# ── 便捷函数 ──

def get_market_regime(hs300_klines=None, sh_klines=None,
                       cyb_klines=None) -> MarketRegime:
    """
    一站式获取市场环境（传入K线或自动拉取）
    """
    scorer = MarketRegimeScorer()

    # 如果未提供K线，自动拉取
    if hs300_klines is None:
        hs300_klines = scorer.fetch_index_klines("000300", 60)
    if sh_klines is None:
        sh_klines = scorer.fetch_index_klines("000001", 60)
    if cyb_klines is None:
        cyb_klines = scorer.fetch_index_klines("399006", 60)

    # 转换为统一格式（如果返回的是dict列表）
    def _to_kline_objs(data):
        if not data:
            return []
        # 如果是已有KLine对象
        if hasattr(data[0], 'close'):
            return data
        # 如果是dict
        if isinstance(data[0], dict):
            return data
        return data

    return scorer.evaluate(
        _to_kline_objs(hs300_klines or []),
        _to_kline_objs(sh_klines or []),
        _to_kline_objs(cyb_klines or []),
    )

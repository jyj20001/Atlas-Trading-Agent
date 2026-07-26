"""Atlas Trading Agent — Backtest Data Context

为回测引擎提供截止到 signal_date 的历史数据快照。
不修改任何评分器代码，通过预填充缓存和数据注入实现。

核心思想:
  SectorScorer 和 MarketRegimeScorer 内部有缓存字典。
  BacktestContext 预先从 snapshot 表读取历史数据，注入到这些缓存中，
  使得评分器在回测时不需要访问网络。

用法:
  ctx = BacktestContext(signal_date="2026-07-20")
  with ctx.using_snapshot(screener):
      output = screener.evaluate(inp)
"""

import json
from datetime import date, datetime
from typing import Optional

from data.snapshot_schema import get_conn
from utils.logger import logger

# ── 指数/板块代码映射（对齐 market_regime.py 和 sector_scorer.py）──

INDEX_MAP = {
    "000300": {"name": "沪深300", "prefix": "sh"},
    "000001": {"name": "上证指数", "prefix": "sh"},
    "399006": {"name": "创业板指", "prefix": "sz"},
}

SECTOR_INDEXES = [
    "sz980017", "sz980021", "sz980022", "sz980024", "sz980014",
    "sz980054", "sz980050", "sz980036", "sz980038",
    "sz980060", "sz980062", "sz980064", "sz980070",
    "sz980080", "sz980082", "sz980084", "sz980090",
    "sz980100", "sz980110", "sz980120", "sz980130",
    "sz980140", "sz980150", "sz980160", "sz980170",
    "sz980180", "sz980190", "sz980200",
]


class BacktestContext:
    """回测数据上下文 — 提供截至 signal_date 的 snapshot 数据"""

    def __init__(self, signal_date: str):
        """
        参数:
            signal_date: 信号日期 YYYY-MM-DD，回测只读取此日期前可见的数据
        """
        self.signal_date = signal_date
        self.conn = get_conn()
        self._sector_cache: dict[str, float] = {}
        self._market_klines: dict[str, list[dict]] = {}
        self._loaded = False

    # ── 数据加载 ──

    def load_all(self):
        """预加载 sector 和 market 快照数据"""
        self._load_sector_returns()
        self._load_market_klines()
        self._loaded = True

    def _load_sector_returns(self):
        """从 sector_snapshot 加载所有板块的 5 日收益率"""
        for idx in SECTOR_INDEXES:
            cur = self.conn.execute(
                "SELECT return_5d FROM sector_snapshot "
                "WHERE index_code = ? AND date(available_time) <= ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (idx, self.signal_date)
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                self._sector_cache[idx] = row[0]

    def _load_market_klines(self):
        """从 market_snapshot 加载三大指数的 60 日 K 线"""
        for code in INDEX_MAP:
            cur = self.conn.execute(
                "SELECT trade_date, open, close, high, low, volume, "
                "ma20, ma50, trend_score, market_status "
                "FROM market_snapshot "
                "WHERE index_code = ? AND date(available_time) <= ? "
                "ORDER BY trade_date DESC LIMIT 60",
                (code, self.signal_date)
            )
            rows = cur.fetchall()
            if rows:
                # 恢复为正序
                klines = []
                for r in reversed(rows):
                    klines.append({
                        "date": r[0], "open": r[1], "close": r[2],
                        "high": r[3], "low": r[4], "volume": r[5],
                        "ma20": r[6], "ma50": r[7],
                        "trend_score": r[8], "market_status": r[9],
                    })
                self._market_klines[code] = klines

    # ── 注入到 Screener ──

    def inject_into(self, screener):
        """将 snapshot 数据注入到 StockScreener 的内部缓存中。
        
        不修改评分器代码，只填充其内部缓存字典，使其跳过网络请求。
        """
        if not self._loaded:
            self.load_all()

        # 1. 注入 SectorScorer._index_cache
        if hasattr(screener, '_sector_scorer'):
            ss = screener._sector_scorer
            if hasattr(ss, '_index_cache'):
                for idx, ret in self._sector_cache.items():
                    ss._index_cache[idx] = ret

        # 2. 注入 MarketRegimeScorer
        # MarketRegimeScorer.evaluate() 接受 K 线作为参数
        # 但 _get_market_regime 在 screener 内部调用 get_market_regime()
        # 我们可以通过注入市场 K 线到上下文来实现零网络
        regime = self._compute_market_regime()
        if regime is not None:
            screener._market_regime = regime

    def _compute_market_regime(self):
        """从 snapshot 计算 MarketRegime"""
        hs300 = self._market_klines.get("000300", [])
        sh = self._market_klines.get("000001", [])
        cyb = self._market_klines.get("399006", [])

        if not hs300 or not sh or not cyb:
            logger.warning(f"市场快照数据不足 ({self.signal_date})")
            return None

        # 复用 MarketRegimeScorer 的评分逻辑
        from core.market_regime import MarketRegimeScorer, MarketRegime
        scorer = MarketRegimeScorer()
        regime = scorer.evaluate(hs300, sh, cyb)
        return regime

    # ── 查找板块指数收益率（供 SectorScorer 兼容）──

    def get_sector_return(self, index_code: str) -> float:
        """获取板块指数 5 日收益率"""
        return self._sector_cache.get(index_code, 0.0)

    def has_data(self) -> bool:
        """检查是否有足够的数据用于回测"""
        return bool(self._market_klines) and bool(self._sector_cache)

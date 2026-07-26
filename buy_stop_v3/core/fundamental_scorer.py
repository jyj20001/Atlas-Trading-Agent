"""Buy Stop V3 — 基本面评分模块 (v2: Snapshot 数据源)

从 announcement_snapshot 表读取公告数据，识别并评分：
  1. 业绩预增（净利润增长 > 50%）
  2. 业绩快报（超预期/扭亏）
  3. 重大合同（金额 / 营收占比）
  4. 回购 / 增持

评分范围：0~15 分

变更历史:
  v1: 直接请求巨潮 API (N+1 问题)
  v2: 读取 announcement_snapshot 快照表，扫描阶段零网络请求
"""

import re
from datetime import date, timedelta
from typing import Optional

from utils.logger import logger
from data.snapshot_query import query_announcements_as_of


# ── 关键词字典 ──

_PRE_INCREASE_KEYWORDS = [
    "预增", "大幅上升", "大幅增长", "同向上升",
    "业绩大增", "利润大增", "净利润增长",
]

_TURNAROUND_KEYWORDS = [
    "扭亏", "扭亏为盈", "实现盈利",
]

_PRE_DECREASE_KEYWORDS = [
    "预减", "预亏", "首亏", "大幅下降",
    "业绩下滑", "利润下滑", "业绩亏损",
]


# ── 公告类型 → snapshot announce_type 映射 ──

_TYPE_FORECAST = "performance_forecast"
_TYPE_REPORT = "performance_report"


# ──────────────────────────────────────────────
# 核心评分器
# ──────────────────────────────────────────────

class FundamentalScorer:
    """基本面评分器 — 读取 announcement_snapshot 表"""

    def __init__(self, lookback_days: int = 30):
        self.lookback = lookback_days
        self._start = (date.today() - timedelta(days=lookback_days)).isoformat()
        self._end = date.today().isoformat()
        # 内存缓存：按关键词存储已读取的快照数据（消除N+1）
        self._batch_cache: dict[str, list[dict]] = {}

    def _set_signal_date(self, signal_date: str):
        """设置信号日期（回测模式用），更新查询范围"""
        from datetime import datetime as dt
        sd = dt.strptime(signal_date, "%Y-%m-%d").date()
        self._start = (sd - timedelta(days=self.lookback)).isoformat()
        self._end = signal_date
        self._batch_cache.clear()

    # ── 从 snapshot 读取（0 网络请求） ──

    def _read_from_snapshot(self, announce_type: str) -> list[dict]:
        """从 announcement_snapshot 读取指定类型公告，结果缓存复用"""
        if announce_type in self._batch_cache:
            return self._batch_cache[announce_type]

        rows = query_announcements_as_of(
            self._end,
            announce_type=announce_type,
        )
        # 过滤日期范围
        results = [r for r in rows if r.get("publish_time", "")[:10] >= self._start]
        self._batch_cache[announce_type] = results
        logger.debug(f"snapshot [{announce_type}]: {len(results)} 条")
        return results

    # ── 对外主接口 ──

    def score_stock(self, code: str, name: str = "") -> dict:
        result = {
            "score": 0,
            "details": [],
            "flags": [],
            "forecasts": [],
            "contracts": [],
        }

        self._score_forecast(code, result)
        self._score_report(code, result)
        self._score_major_contract(code, result)
        self._score_buyback(code, result)
        result["score"] = max(0, min(15, result["score"]))
        return result

    # ── 1. 业绩预告评分（最多 +8 分） ──

    def _score_forecast(self, code: str, result: dict) -> None:
        forecasts = [r for r in self._read_from_snapshot(_TYPE_FORECAST)
                     if r["code"] == code]
        if not forecasts:
            return

        result["forecasts"] = forecasts

        for row in forecasts:
            title_info = self._classify_forecast_from_dict(row)

            if title_info["type"] == "预增":
                chg = self._profit_change_mid(row)
                if chg is not None and chg >= 100:
                    result["score"] += 8
                    result["details"].append(f"业绩预增{chg:.0f}% (+8)")
                elif chg is not None and chg >= 50:
                    result["score"] += 6
                    result["details"].append(f"业绩预增{chg:.0f}% (+6)")
                else:
                    result["score"] += 4
                    result["details"].append("业绩预增（幅度未明确）(+4)")

            elif title_info["type"] == "扭亏":
                result["score"] += 5
                result["details"].append("扭亏为盈 (+5)")

            elif title_info["type"] == "预减":
                chg = self._profit_change_mid(row)
                if chg is not None and chg <= -50:
                    result["flags"].append(f"业绩预减{chg:.0f}%")
                else:
                    result["flags"].append("业绩预减")

    # ── 2. 业绩快报评分（最多 +5 分） ──

    def _score_report(self, code: str, result: dict) -> None:
        reports = [r for r in self._read_from_snapshot(_TYPE_REPORT)
                   if r["code"] == code]
        if not reports:
            return
        for rp in reports:
            result["score"] += 3
            result["details"].append("发布业绩快报 (+3)")

    # ── 3. 重大合同评分（最多 +4 分） ──

    def _score_major_contract(self, code: str, result: dict) -> None:
        contracts = [a for a in self._read_from_snapshot("major_contract")
                     if a["code"] == code]
        if contracts:
            latest = contracts[0]
            title = latest.get("title", "")
            result["contracts"].append(latest)
            result["score"] += 4
            result["details"].append(f"重大合同/中标: {title[:40]}... (+4)")

    # ── 4. 回购/增持评分（最多 +2 分） ──

    def _score_buyback(self, code: str, result: dict) -> None:
        buybacks = [a for a in self._read_from_snapshot("buyback")
                    if a["code"] == code]
        if buybacks:
            result["score"] += 2
            result["details"].append("股份回购/增持公告 (+2)")

    # ── 辅助 ──

    @staticmethod
    def _profit_change_mid(row: dict) -> Optional[float]:
        """从 snapshot dict 估算利润变动中值"""
        low = row.get("change_pct_lower")
        high = row.get("change_pct_upper")
        if low is not None and high is not None:
            return (low + high) / 2
        return low or high

    @staticmethod
    def _classify_forecast_from_dict(row: dict) -> dict:
        """根据 snapshot dict 分类预告类型"""
        report_type = row.get("report_type", "")
        forecast_type = row.get("forecast_type", "")
        title = f"{report_type} {forecast_type}"
        chg = FundamentalScorer._profit_change_mid(row)

        if any(kw in title for kw in _PRE_INCREASE_KEYWORDS):
            return {"type": "预增"}
        if any(kw in title for kw in _TURNAROUND_KEYWORDS):
            return {"type": "扭亏"}
        if any(kw in title for kw in _PRE_DECREASE_KEYWORDS):
            return {"type": "预减"}

        if chg is not None:
            if chg >= 30:
                return {"type": "预增"}
            elif chg <= -20:
                return {"type": "预减"}

        return {"type": "预警"}


# ──────────────────────────────────────────────
# 工具函数（与 v1 接口完全兼容）
# ──────────────────────────────────────────────

def merge_fundamental_score(screener_score: dict,
                             fundamental_score: dict) -> dict:
    new_score = dict(screener_score)
    f_score = fundamental_score.get("score", 0)
    new_score["fundamental"] = f_score
    new_score["total"] = new_score.get("total", 0) + f_score
    return new_score


def format_fundamental_details(fundamental_score: dict) -> str:
    parts = []
    for d in fundamental_score.get("details", []):
        parts.append(d)
    for f in fundamental_score.get("flags", []):
        parts.append(f"⚠️ {f}")
    if not parts:
        return "无近期基本面信号"
    return "; ".join(parts)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "000977"
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    fs = FundamentalScorer(lookback_days=90)
    result = fs.score_stock(code, name)
    print(f"\n📊 基本面评分 — {code} {name}")
    print(f"{'='*50}")
    print(f"  总分: {result['score']}/15")
    print(f"  详情:")
    for d in result.get("details", []):
        print(f"    ✅ {d}")
    for f in result.get("flags", []):
        print(f"    ⚠️ {f}")
    if not result["details"] and not result["flags"]:
        print("    无近期基本面信号")
    print(f"  预告/快报: {len(result.get('forecasts', []))} 条")
    print(f"  合同公告: {len(result.get('contracts', []))} 条")

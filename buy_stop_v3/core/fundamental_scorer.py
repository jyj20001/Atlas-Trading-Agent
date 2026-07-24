"""
Buy Stop V3 — 基本面评分模块

从巨潮资讯抓取公告，识别并评分：
  1. 业绩预增（净利润增长 > 50%）
  2. 业绩快报（超预期/扭亏）
  3. 重大合同（金额 / 营收占比）
  4. 回购 / 增持

评分范围：0~15 分（占用screener预留的板块10分 + 额外加分）

合并到 StockScreener 方式：
  fundamental_scorer 返回 dict，screener 的 _scorer 中加上 score_fundamental

典型用法：
  from core.fundamental_scorer import FundamentalScorer
  fs = FundamentalScorer()
  score = fs.score_stock("000977", "浪潮信息")
"""

import re
from datetime import date, timedelta
from typing import Optional

from utils.logger import logger
from data.cninfo_fetcher import (
    search_performance_forecasts,
    search_performance_reports,
    search_stock_announcements,
)


# ── 关键词字典 ──

# 预增关键词
_PRE_INCREASE_KEYWORDS = [
    "预增", "大幅上升", "大幅增长", "同向上升",
    "业绩大增", "利润大增", "净利润增长",
]

# 扭亏关键词
_TURNAROUND_KEYWORDS = [
    "扭亏", "扭亏为盈", "实现盈利",
]

# 预减/预亏关键词
_PRE_DECREASE_KEYWORDS = [
    "预减", "预亏", "首亏", "大幅下降",
    "业绩下滑", "利润下滑", "业绩亏损",
]

# 重大合同关键词
_MAJOR_CONTRACT_KEYWORDS = [
    "重大合同", "中标", "中标公告", "签订合同",
    "重大协议", "战略合作", "重大订单",
]

# 回购/增持关键词
_BUYBACK_KEYWORDS = [
    "回购", "股份回购", "增持", "增持计划",
    "回购报告书", "增持公告",
]


# ──────────────────────────────────────────────
# 核心评分器
# ──────────────────────────────────────────────

class FundamentalScorer:
    """
    基本面评分器

    每次调用会访问巨潮资讯网获取最新公告数据，请合理控制调用频率。
    """

    def __init__(self, lookback_days: int = 30):
        """
        参数:
            lookback_days: 搜索过去多少天的公告（默认30天）
        """
        self.lookback = lookback_days
        self._start = (date.today() - timedelta(days=lookback_days)).isoformat()
        self._end = date.today().isoformat()

    # ── 对外主接口 ──

    def score_stock(self, code: str, name: str = "") -> dict:
        """
        对单只股票进行基本面评分

        参数:
            code: 股票代码
            name: 股票名称（可选，仅用于日志）

        返回:
            {
                "score": 0~15,
                "details": [str, ...],  # 评分理由
                "flags": [str, ...],    # 风险标记
                "forecasts": [...],     # 匹配到的业绩预告
                "contracts": [...],     # 匹配到的重大合同
            }
        """
        result = {
            "score": 0,
            "details": [],
            "flags": [],
            "forecasts": [],
            "contracts": [],
        }

        # 1. 业绩预告评分（最多 +8 分）
        self._score_forecast(code, result)

        # 2. 业绩快报评分（最多 +5 分）
        self._score_report(code, result)

        # 3. 重大合同评分（最多 +4 分）
        self._score_major_contract(code, result)

        # 4. 回购增持加分（最多 +2 分）
        self._score_buyback(code, result)

        # 总分限制 0~15
        result["score"] = max(0, min(15, result["score"]))

        return result

    # ── 1. 业绩预告评分 ──

    def _score_forecast(self, code: str, result: dict) -> None:
        """搜索业绩预告并评分"""
        try:
            forecasts = search_performance_forecasts(
                start_date=self._start, end_date=self._end, page=1, page_size=30
            )
        except Exception as e:
            logger.debug(f"业绩预告搜索失败: {e}")
            return

        # 过滤属于本股票的
        stock_forecasts = [f for f in forecasts if f.code == code]
        if not stock_forecasts:
            return

        result["forecasts"] = stock_forecasts

        for pf in stock_forecasts:
            title_info = self._classify_forecast(pf)

            if title_info["type"] == "预增":
                # 根据增长幅度评分
                chg = pf.profit_change_pct
                if chg is not None and chg >= 100:
                    result["score"] += 8
                    result["details"].append(
                        f"业绩预增{chg:.0f}% (+8)"
                    )
                elif chg is not None and chg >= 50:
                    result["score"] += 6
                    result["details"].append(
                        f"业绩预增{chg:.0f}% (+6)"
                    )
                else:
                    result["score"] += 4
                    result["details"].append(
                        f"业绩预增（幅度未明确）(+4)"
                    )

            elif title_info["type"] == "扭亏":
                result["score"] += 5
                result["details"].append("扭亏为盈 (+5)")

            elif title_info["type"] == "预减":
                chg = pf.profit_change_pct
                if chg is not None and chg <= -50:
                    result["flags"].append(f"业绩预减{chg:.0f}%")
                else:
                    result["flags"].append("业绩预减")

    # ── 2. 业绩快报评分 ──

    def _score_report(self, code: str, result: dict) -> None:
        """搜索业绩快报并评分"""
        try:
            reports = search_performance_reports(
                start_date=self._start, end_date=self._end, page=1, page_size=30
            )
        except Exception as e:
            logger.debug(f"业绩快报搜索失败: {e}")
            return

        stock_reports = [r for r in reports if r.code == code]
        if not stock_reports:
            return

        # 快报本身说明公司已披露正式财务数据，给予正面评分
        for rp in stock_reports:
            result["score"] += 3
            result["details"].append(f"发布业绩快报 (+3)")

    # ── 3. 重大合同评分 ──

    def _score_major_contract(self, code: str, result: dict) -> None:
        """搜索重大合同公告并评分"""
        try:
            contracts = search_stock_announcements(
                stock_code=code,
                keyword="重大合同",
                start_date=self._start,
                end_date=self._end,
            )
        except Exception as e:
            logger.debug(f"重大合同搜索失败: {e}")
            return

        if not contracts:
            # 也试一下"中标"关键词
            try:
                contracts = search_stock_announcements(
                    stock_code=code,
                    keyword="中标",
                    start_date=self._start,
                    end_date=self._end,
                )
            except Exception:
                return

        if contracts:
            # 取最新一条
            latest = contracts[0]
            title = latest.get("title", "")
            result["contracts"].append(latest)

            result["score"] += 4
            result["details"].append(f"重大合同/中标: {title[:40]}... (+4)")

    # ── 4. 回购/增持评分 ──

    def _score_buyback(self, code: str, result: dict) -> None:
        """搜索回购/增持公告并评分"""
        try:
            buybacks = search_stock_announcements(
                stock_code=code,
                keyword="回购",
                start_date=self._start,
                end_date=self._end,
            )
        except Exception as e:
            logger.debug(f"回购搜索失败: {e}")
            return

        if buybacks:
            result["score"] += 2
            result["details"].append(f"股份回购/增持公告 (+2)")

    # ── 辅助：预告分类 ──

    @staticmethod
    def _classify_forecast(pf) -> dict:
        """
        根据 PerformanceForecast 的标题信息分类
        返回: {"type": "预增"|"扭亏"|"预减"|"预警"|"其他"}
        """
        title_text = f"{pf.report_type} {pf.forecast_type}"

        # 检查净利润变动方向
        chg = pf.profit_change_pct

        # 从 report_type 推断
        if any(kw in title_text for kw in _PRE_INCREASE_KEYWORDS):
            return {"type": "预增"}
        if any(kw in title_text for kw in _TURNAROUND_KEYWORDS):
            return {"type": "扭亏"}
        if any(kw in title_text for kw in _PRE_DECREASE_KEYWORDS):
            return {"type": "预减"}

        # 如果标题无法判定，尝试从数据推断
        if chg is not None:
            if chg >= 30:
                return {"type": "预增"}
            elif chg <= -20:
                return {"type": "预减"}

        return {"type": "预警"}


# ──────────────────────────────────────────────
# 工具函数：合并到 StockScreener 评分
# ──────────────────────────────────────────────

def merge_fundamental_score(screener_score: dict,
                             fundamental_score: dict) -> dict:
    """
    将基本面评分合并到 screener 的评分 dict 中

    参数:
        screener_score: StockScreener._scorer() 返回的 dict
            {"trend": 20, "structure": 25, ..., "total": 75}
        fundamental_score: FundamentalScorer.score_stock() 返回的 dict
            {"score": 8, "details": [...], ...}

    返回:
        更新后的 dict（包含新的 score_fundamental 和调整后的 total）
    """
    new_score = dict(screener_score)
    f_score = fundamental_score.get("score", 0)

    new_score["fundamental"] = f_score
    new_score["total"] = new_score.get("total", 0) + f_score

    return new_score


def format_fundamental_details(fundamental_score: dict) -> str:
    """格式化基本面详情为可读字符串"""
    parts = []
    for d in fundamental_score.get("details", []):
        parts.append(d)
    for f in fundamental_score.get("flags", []):
        parts.append(f"⚠️ {f}")

    if not parts:
        return "无近期基本面信号"

    return "; ".join(parts)


# ──────────────────────────────────────────────
# 主入口（直接运行做演示）
# ──────────────────────────────────────────────

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
        print(f"    无近期基本面信号")
    print(f"  预告/快报: {len(result.get('forecasts', []))} 条")
    print(f"  合同公告: {len(result.get('contracts', []))} 条")

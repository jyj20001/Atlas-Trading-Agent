"""
Buy Stop V3 — 候选股票筛选引擎

处理流水线：
  1. trend_filter          — 趋势过滤（MA200 + 接近突破位）
  2. breakout_setup        — 突破结构计算（Buy Stop Price）
  3. volume_filter         — 成交量确认
  4. turnover_filter       — 换手率评估
  5. fundamental_score     — 基本面评分（预增/快报/合同/回购）
  6. market_regime         — 市场环境评分（0~5）
  7. sector_scorer         — 板块强度评分（0~10）
  8. breakout_stage        — 突破生命周期识别
  9. risk_flagger          — A股特殊风险标记
  10. scorer               — 最终评分 + 评级 + 硬性过滤

评分体系（最高130分）：
  Technical:  0~100  趋势20 + 结构25 + 量能20 + 换手15 + 风险10 + 板块10
  Fundamental: 0~15  预增/快报/合同/回购（时间衰减）
  Market:      0~5   三大指数趋势
  Sector:      0~10  个股 vs 板块超额收益
  ─────────────────────────────────
  Combined:   130分

突破生命周期：
  EARLY_BREAKOUT  → ✅ Buy Stop
  TRENDING        → ✅ 谨慎Buy Stop
  EXTENDED        → 🚫 降低评级
  CLIMAX          → 🚫 NO_TRADE
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from utils.logger import logger
from utils.helpers import get_market_cap_category
from config.settings import BUY_STOP
from data.types import KLine, BreakoutSignal, ScreenerResult
from core.fundamental_scorer import (
    FundamentalScorer, merge_fundamental_score, format_fundamental_details,
)
from core.market_regime import MarketRegimeScorer, get_market_regime, MarketRegime
from core.sector_scorer import SectorScorer, SectorScore
from core.breakout_stage import BreakoutStageIdentifier, BreakoutStage


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class ScreenerInput:
    symbol: str
    name: str
    klines: list[KLine]
    market_cap: float = 0.0
    sector: str = ""


@dataclass
class ScreenerOutput:
    passed: bool
    signal: Optional[BreakoutSignal] = None
    reason: str = ""
    risk_flags: list[str] = field(default_factory=list)
    fundamental_score: int = 0
    fundamental_details: str = ""
    market_score: int = 0
    market_status: str = ""
    sector_score: int = 0
    sector_details: str = ""
    breakout_stage: str = ""
    combined_score: int = 0
    recommendation: str = ""


# ──────────────────────────────────────────────
# 核心筛选器
# ──────────────────────────────────────────────

class StockScreener:

    def __init__(self, enable_fundamental: bool = True,
                 fundamental_lookback_days: int = 90):
        self.params = BUY_STOP
        self._enable_fundamental = enable_fundamental
        self._fundamental_scorer = (
            FundamentalScorer(lookback_days=fundamental_lookback_days)
            if enable_fundamental else None
        )
        self._market_scorer = MarketRegimeScorer()
        self._sector_scorer = SectorScorer()
        self._stage_identifier = BreakoutStageIdentifier()
        # 缓存市场环境（同一轮筛选只算一次）
        self._market_regime: Optional[MarketRegime] = None

    # ── 主入口 ──

    def evaluate(self, inp: ScreenerInput) -> ScreenerOutput:
        klines = inp.klines
        if len(klines) < 60:
            return ScreenerOutput(False, None, f"K线不足({len(klines)}/<60)")

        latest = klines[-1]
        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        volumes = [k.volume for k in klines]

        # 1. 趋势过滤
        trend = self._trend_filter(closes, latest.close, highs)
        if trend["failed"]:
            return ScreenerOutput(False, None, trend["reason"])

        # 2. 突破结构
        setup = self._breakout_setup(klines, latest, highs)

        # 3. 成交量
        vol_check = self._volume_filter(volumes[-20:], latest.volume)

        # 4. 换手率
        turn_check = self._turnover_filter(inp.market_cap, latest.amount, latest.close)

        # 5. 风险标记
        risk = self._risk_flagger(klines, latest, highs)

        # 6. 基本面
        fundamental = {"score": 0, "details": [], "flags": []}
        if self._enable_fundamental and self._fundamental_scorer:
            try:
                code = inp.symbol.split(".")[-1] if "." in inp.symbol else inp.symbol
                fundamental = self._fundamental_scorer.score_stock(code, inp.name)
            except Exception as e:
                logger.debug(f"基本面评分失败 {inp.symbol}: {e}")

        # 7. 市场环境
        market = self._get_market_regime()

        # 8. 板块强度
        try:
            code_num = inp.symbol.split(".")[-1] if "." in inp.symbol else inp.symbol
            sector_result = self._sector_scorer.evaluate(
                code_num, inp.sector, klines
            )
        except Exception as e:
            logger.debug(f"板块评分失败 {inp.symbol}: {e}")
            sector_result = SectorScore(0, "", 0, 0, 0)

        # 9. 突破生命周期
        stage_result = self._stage_identifier.evaluate(
            klines,
            high20=setup["high20"],
            high60=setup["high60"],
            consecutive_limit=risk["consecutive_limit"],
            change_5d_pct=setup["change_5d_pct"],
            days_since_breakout=setup["days_since_breakout"],
        )

        # 10. 评分 + 过滤 + 推荐
        score = self._scorer(
            trend, setup, vol_check, turn_check, risk, fundamental,
            market, sector_result, stage_result,
        )

        # ── 硬性过滤 ──
        recommendation = score["recommendation"]
        is_passed = recommendation in ("BUY_STOP", "CAUTION_BUY")
        fatal_reason = ""

        if recommendation == "NO_TRADE":
            is_passed = False
            if stage_result.stage == BreakoutStage.CLIMAX:
                fatal_reason = f"高潮段(连续{risk['consecutive_limit']}天涨停)，禁止交易"
            else:
                fatal_reason = "综合评估不适合交易"

        # ── 构造 BreakoutSignal ──
        signal = None
        if not risk.get("fatal"):
            signal = BreakoutSignal(
                symbol=inp.symbol, name=inp.name,
                price=latest.close,
                breakout_price=setup["buy_stop_price"],
                ma200=trend["ma200"], above_ma200=True,
                volume_ratio=vol_check["ratio"],
                turnover_pct=turn_check["rate"],
                change_5d_pct=setup["change_5d_pct"],
                consecutive_limit=risk["consecutive_limit"],
                days_since_breakout=setup["days_since_breakout"],
                score_trend=score["trend"], score_structure=score["structure"],
                score_volume=score["volume"], score_turnover=score["turnover"],
                score_sector=sector_result.score, score_risk=score["risk"],
                total_score=score["total"],
                suggestion=self._suggestion_text(recommendation),
                stop_loss=setup["stop_loss"], target=setup["target"],
                risk_reward=setup["risk_reward"],
            )

        # 如果风险fatal也禁止
        if risk.get("fatal"):
            is_passed = False
            fatal_reason = risk["fatal_reason"]

        return ScreenerOutput(
            passed=is_passed, signal=signal,
            reason=fatal_reason or score.get("note", ""),
            risk_flags=risk["flags"] + ([stage_result.stage_name]
                                       if stage_result.stage != BreakoutStage.EARLY_BREAKOUT
                                       else []),
            fundamental_score=fundamental.get("score", 0),
            fundamental_details=format_fundamental_details(fundamental),
            market_score=market.trend_score,
            market_status=market.market_status,
            sector_score=sector_result.score,
            sector_details=sector_result.description,
            breakout_stage=stage_result.stage.value,
            combined_score=score["total"],
            recommendation=recommendation,
        )

    # ── 市场环境（带缓存） ──

    def _get_market_regime(self) -> MarketRegime:
        if self._market_regime is None:
            try:
                self._market_regime = get_market_regime()
            except Exception as e:
                logger.debug(f"市场环境评分失败: {e}")
                self._market_regime = MarketRegime(0, "neutral")
        return self._market_regime

    # ── 各过滤步骤 ──

    def _trend_filter(self, closes, price, highs) -> dict:
        result = {"failed": False, "reason": "", "ma200": None}
        if len(closes) < 200:
            result["failed"] = True
            result["reason"] = f"数据不足200天(仅{len(closes)}天)"
            return result
        ma200 = sum(closes[-200:]) / 200
        result["ma200"] = ma200
        if price <= ma200:
            result["failed"] = True
            result["reason"] = f"价格{price:.2f} <= MA200{ma200:.2f}"
            return result
        high20 = max(highs[-20:])
        dist_to_high20 = (price - high20) / high20 * 100
        if dist_to_high20 < -5:
            result["failed"] = True
            result["reason"] = (f"距离20日高{high20:.2f}过远"
                                f"({dist_to_high20:+.2f}% < -5%)")
            return result
        result["high20"] = high20
        result["dist_to_high20"] = dist_to_high20
        return result

    def _breakout_setup(self, klines, latest, highs) -> dict:
        n = len(klines)
        high20 = max(highs[-20:])
        high60 = max(highs[-60:]) if n >= 60 else max(highs)
        yesterday_high = klines[-2].high if n >= 2 else latest.high
        buy_stop_price = round(yesterday_high * 1.005, 2)
        days_since_breakout = 0
        for k in reversed(klines[:-1]):
            if k.high >= high20:
                break
            days_since_breakout += 1
        change_5d_pct = 0.0
        if n >= 6:
            change_5d_pct = ((latest.close - klines[-6].close)
                             / klines[-6].close * 100)
        low20 = min(k.low for k in klines[-20:])
        stop_loss = round(low20 * 0.995, 2)
        target = round(buy_stop_price * 1.15, 2)
        rps = buy_stop_price - stop_loss
        rwr = round((target - buy_stop_price) / rps, 2) if rps > 0 else 0
        return {"high20": high20, "high60": high60,
                "yesterday_high": yesterday_high,
                "buy_stop_price": buy_stop_price,
                "stop_loss": stop_loss, "target": target,
                "risk_reward": rwr,
                "days_since_breakout": days_since_breakout,
                "change_5d_pct": change_5d_pct}

    def _volume_filter(self, recent_volumes, current_volume) -> dict:
        if len(recent_volumes) < 2:
            return {"sufficient": False, "ratio": 0.0}
        avg = sum(recent_volumes[:-1]) / (len(recent_volumes) - 1)
        ratio = current_volume / avg if avg > 0 else 0
        return {"sufficient": ratio >= self.params["VOLUME_RATIO"],
                "ratio": round(ratio, 2)}

    def _turnover_filter(self, market_cap, amount, price) -> dict:
        if market_cap <= 0 or amount <= 0:
            return {"rate": None, "normal": True, "warning": False}
        turnover_rate = amount / market_cap * 100
        cap_class = get_market_cap_category(market_cap)
        limits = {"large_cap": (1.5, 5.0), "mid_cap": (3.0, 10.0),
                  "small_cap": (5.0, 15.0)}
        low, high = limits.get(cap_class, (0, 100))
        return {"rate": round(turnover_rate, 2),
                "normal": low <= turnover_rate <= high,
                "warning": turnover_rate > high,
                "range": f"{low}%-{high}%"}

    def _risk_flagger(self, klines, latest, highs) -> dict:
        flags = []
        fatal = False
        fatal_reason = ""
        n = len(klines)

        consecutive_limit = 0
        for i in range(min(7, n - 1)):
            idx = n - 2 - i
            chg = ((klines[idx].close - klines[idx - 1].close)
                   / klines[idx - 1].close * 100) if idx > 0 else 0
            if chg >= 9.5:
                consecutive_limit += 1
            else:
                break
        if consecutive_limit >= 3:
            flags.append(f"连续{consecutive_limit}天涨停(>9.5%)")
            if consecutive_limit >= self.params["MAX_CONSECUTIVE_LIMIT"]:
                fatal = True
                fatal_reason = f"连续{consecutive_limit}天涨停，高位加速"

        if n >= 6:
            change_5d = ((latest.close - klines[-6].close)
                         / klines[-6].close * 100)
            if change_5d > 30:
                flags.append(f"5日涨幅{change_5d:.1f}% > 30%")
            if change_5d > 50:
                if self.params["EXCLUDE_50D_CHANGE"]:
                    fatal = True
                    fatal_reason = f"5日涨幅{change_5d:.1f}% > 50%，排除"

        high20 = max(highs[-20:])
        days_since = 0
        for k in reversed(klines[:-1]):
            if k.high >= high20:
                break
            days_since += 1
        if days_since > self.params["BREAKOUT_WINDOW_DAYS"]:
            flags.append(f"突破20日高已过{days_since}天"
                         f"(窗口{self.params['BREAKOUT_WINDOW_DAYS']}天)")

        body = abs(latest.close - latest.open)
        upper_shadow = latest.high - max(latest.close, latest.open)
        total_range = latest.high - latest.low
        if total_range > 0:
            upper_ratio = upper_shadow / total_range
            if (latest.close < latest.open and upper_ratio > 0.6
                    and latest.volume
                    > sum(k.volume for k in klines[-5:-1]) / 4 * 1.5):
                flags.append("高位放量长上影线(警惕派发)")

        return {"flags": flags, "fatal": fatal,
                "fatal_reason": fatal_reason,
                "consecutive_limit": consecutive_limit}

    # ── 评分 ──

    def _scorer(self, trend, setup, volume, turnover, risk,
                 fundamental, market, sector, stage) -> dict:
        """
        130分制评分：
          Technical:  100 (趋势20+结构25+量能20+换手15+风险10+板块10)
          Fundamental: 15 (实际值)
          Market:       5
          Sector:      10
        """
        # ── Technical (100) ──
        score_trend = 20
        dist = trend.get("dist_to_high20", 0)
        if dist < -3:
            score_trend = 15
        elif dist < -1:
            score_trend = 18

        score_structure = 25
        dsb = setup.get("days_since_breakout", 0)
        if dsb > 5:
            score_structure = 10
        elif dsb > 3:
            score_structure = 18
        elif dsb > 1:
            score_structure = 22
        chg_5d = setup.get("change_5d_pct", 0)
        if abs(chg_5d) > 15:
            score_structure = max(5, score_structure - 8)

        if volume["sufficient"]:
            score_volume = 20
        elif volume["ratio"] >= 1.2:
            score_volume = 12
        else:
            score_volume = int(volume["ratio"] * 10)
            score_volume = max(0, min(10, score_volume))

        if turnover.get("rate") is None:
            score_turnover = 7
        elif turnover["warning"]:
            score_turnover = 3
        elif turnover["normal"]:
            score_turnover = 15
        else:
            score_turnover = 8

        score_risk = 10 - len(risk.get("flags", [])) * 3
        score_risk = max(0, min(10, score_risk))
        if risk.get("fatal"):
            score_risk = 0

        tech = min(score_trend + score_structure + score_volume
                   + score_turnover + score_risk, 100)

        # ── Fundamental (0~15) ──
        fund_raw = fundamental.get("score", 0) if fundamental else 0
        fund = min(fund_raw, 15)

        # ── Market (0~5) ──
        market_score = min(market.trend_score, 5)

        # ── Sector (0~10) ──
        sector_score = min(sector.score, 10)

        raw_total = tech + fund + market_score + sector_score

        # ── 硬性过滤 + 推荐 ──
        stage_enum = stage.stage
        recommendation = "BUY_STOP"
        note = ""

        # CLIMAX → 禁止
        if stage_enum == BreakoutStage.CLIMAX:
            recommendation = "NO_TRADE"
            note = "高潮阶段，禁止交易"

        # EXTENDED → 降级（但高分仍可谨慎参与）
        elif stage_enum == BreakoutStage.EXTENDED:
            if raw_total >= 85:
                recommendation = "CAUTION_BUY"
                note = "延伸段，谨慎参与"
            elif raw_total >= 75:
                recommendation = "CAUTION_BUY"
                note = "延伸段低分，仅观察"
            else:
                recommendation = "NO_TRADE"
                note = "延伸段，评分不足"

        # Market Bear → 高分才可
        elif market.market_status == "bear":
            if raw_total >= 105:
                recommendation = "CAUTION_BUY"
                note = "熊市，仅高分可参与"
            else:
                recommendation = "NO_TRADE"
                note = "熊市环境，评分不足"

        # NO_BREAKOUT → 不交易
        elif stage_enum in (None,):
            from core.breakout_stage import BreakoutStage as BS
            if stage_enum == BS.NO_BREAKOUT:
                recommendation = "NO_TRADE"
                note = "未识别到突破结构"

        # C级以下不推荐
        if recommendation in ("BUY_STOP", "CAUTION_BUY"):
            if raw_total < 75:
                recommendation = "NO_TRADE"
                note = "综合评分不足75"

        total = raw_total

        return {
            "trend": score_trend, "structure": score_structure,
            "volume": score_volume, "turnover": score_turnover,
            "risk": score_risk, "tech": tech,
            "fundamental": fund,
            "market": market_score, "sector": sector_score,
            "total": total,
            "recommendation": recommendation,
            "note": note,
        }

    # ── 评级 ──

    @staticmethod
    def _suggestion_text(recommendation: str) -> str:
        mapping = {
            "BUY_STOP": "Buy Stop 候选",
            "CAUTION_BUY": "谨慎参与",
            "NO_TRADE": "不适合交易",
        }
        return mapping.get(recommendation, "观望")

    @staticmethod
    def rating_from_score(combined: int) -> str:
        if combined >= 105:
            return "A+"
        elif combined >= 95:
            return "A"
        elif combined >= 85:
            return "B+"
        elif combined >= 75:
            return "B"
        elif combined >= 65:
            return "C"
        return "NO"


# ──────────────────────────────────────────────
# 批量筛选
# ──────────────────────────────────────────────

def run_screener(inputs: list[ScreenerInput],
                 enable_fundamental: bool = True) -> ScreenerResult:
    screener = StockScreener(enable_fundamental=enable_fundamental)
    candidates: list[BreakoutSignal] = []
    eliminated: list[dict] = []

    for inp in inputs:
        output = screener.evaluate(inp)
        if output.passed and output.signal:
            candidates.append(output.signal)
        else:
            eliminated.append({
                "symbol": inp.symbol,
                "name": inp.name,
                "reason": output.reason,
                "risk_flags": output.risk_flags,
                "breakout_stage": output.breakout_stage,
                "recommendation": output.recommendation,
            })

    result = ScreenerResult(
        scan_date=date.today().isoformat(),
        total_stocks=len(inputs),
        candidates=candidates,
        eliminated=eliminated,
    )

    logger.info(f"筛选完成: {len(inputs)}只 -> "
                f"{len(candidates)}候选 / {len(eliminated)}淘汰")

    result.candidates.sort(key=lambda x: x.total_score, reverse=True)
    return result

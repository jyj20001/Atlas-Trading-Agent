"""
Buy Stop V3 — 突破生命周期识别模块

识别股价突破所处的生命周期阶段。
用于辅助 Buy Stop 决策：只做 EARLY_BREAKOUT 和部分 TRENDING。

阶段定义：
  EARLY_BREAKOUT  — 刚突破，<=5天，涨幅<20%     ✅ 最佳买入窗口
  TRENDING        — 趋势运行中，5~15天，涨幅20~50%
  EXTENDED        — 延伸段，距突破>10天或涨幅>30%  ⚠️ 风险增大
  CLIMAX          — 高潮段，连板/翻倍/>50%         🚫 禁止追涨
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BreakoutStage(Enum):
    EARLY_BREAKOUT = "EARLY_BREAKOUT"
    TRENDING = "TRENDING"
    EXTENDED = "EXTENDED"
    CLIMAX = "CLIMAX"
    NO_BREAKOUT = "NO_BREAKOUT"


@dataclass
class BreakoutStageResult:
    """突破生命周期评估结果"""
    stage: BreakoutStage
    stage_name: str                # 中文名
    allow_buy_stop: bool           # 是否允许Buy Stop
    days_since_breakout: int       # 距突破天数
    change_since_breakout: float   # 突破后涨幅%
    consecutive_limit: int         # 连续涨停天数
    change_5d_pct: float           # 5日涨幅%


# ──────────────────────────────────────────────
# 核心识别器
# ──────────────────────────────────────────────

class BreakoutStageIdentifier:
    """
    突破生命周期识别器

    输入K线数据，输出当前所处的突破阶段。
    """

    def evaluate(self, klines: list, high20: float, high60: float,
                  consecutive_limit: int = 0, change_5d_pct: float = 0.0,
                  days_since_breakout: Optional[int] = None
                  ) -> BreakoutStageResult:
        """
        识别突破生命周期阶段

        参数:
            klines: 日K线列表（最新在最后）
            high20: 20日最高价
            high60: 60日最高价
            consecutive_limit: 连续涨停天数
            change_5d_pct: 5日涨幅%
            days_since_breakout: 外部传入的距突破天数（若None则内部计算）

        返回:
            BreakoutStageResult
        """
        n = len(klines)
        latest = klines[-1]
        latest_close = latest.close if hasattr(latest, 'close') else float(latest[-1])

        # 计算距突破天数
        if days_since_breakout is not None:
            days_since = days_since_breakout
        else:
            days_since = 0
            for k in reversed(klines[:-1]):
                k_high = k.high if hasattr(k, 'high') else float(k[3])
                if k_high >= high20:
                    break
                days_since += 1

        # 突破参考价：首次突破20日高那天的收盘价
        breakout_price = None
        if days_since < n - 1:
            ref_idx = n - 2 - days_since
            if 0 <= ref_idx < n:
                ref = klines[ref_idx]
                breakout_price = ref.close if hasattr(ref, 'close') else float(ref[2])

        change_since = 0.0
        if breakout_price and breakout_price > 0:
            change_since = (latest_close - breakout_price) / breakout_price * 100

        # ── CLIMAX 检测（优先级最高） ──
        if consecutive_limit >= 3:
            return BreakoutStageResult(
                stage=BreakoutStage.CLIMAX, stage_name="高潮段",
                allow_buy_stop=False,
                days_since_breakout=days_since,
                change_since_breakout=round(change_since, 2),
                consecutive_limit=consecutive_limit,
                change_5d_pct=change_5d_pct,
            )

        if change_5d_pct > 50 or change_since > 100:
            return BreakoutStageResult(
                stage=BreakoutStage.CLIMAX, stage_name="高潮段",
                allow_buy_stop=False,
                days_since_breakout=days_since,
                change_since_breakout=round(change_since, 2),
                consecutive_limit=consecutive_limit,
                change_5d_pct=change_5d_pct,
            )

        # ── EXTENDED 检测 ──
        if days_since > 10 or change_5d_pct > 30:
            return BreakoutStageResult(
                stage=BreakoutStage.EXTENDED, stage_name="延伸段",
                allow_buy_stop=False,
                days_since_breakout=days_since,
                change_since_breakout=round(change_since, 2),
                consecutive_limit=consecutive_limit,
                change_5d_pct=change_5d_pct,
            )

        # ── TRENDING 检测 ──
        if 5 <= days_since <= 15 and 20 <= change_5d_pct <= 50:
            return BreakoutStageResult(
                stage=BreakoutStage.TRENDING, stage_name="趋势运行",
                allow_buy_stop=True,
                days_since_breakout=days_since,
                change_since_breakout=round(change_since, 2),
                consecutive_limit=consecutive_limit,
                change_5d_pct=change_5d_pct,
            )

        # ── EARLY_BREAKOUT（最佳窗口）──
        # 放宽条件：<=5天，涨幅<20%，可带量
        if days_since <= 5 and change_5d_pct < 20:
            return BreakoutStageResult(
                stage=BreakoutStage.EARLY_BREAKOUT, stage_name="早期突破",
                allow_buy_stop=True,
                days_since_breakout=days_since,
                change_since_breakout=round(change_since, 2),
                consecutive_limit=consecutive_limit,
                change_5d_pct=change_5d_pct,
            )

        # ── 默认：未突破或无法识别 ──
        return BreakoutStageResult(
            stage=BreakoutStage.NO_BREAKOUT, stage_name="未突破",
            allow_buy_stop=False,
            days_since_breakout=days_since,
            change_since_breakout=round(change_since, 2),
            consecutive_limit=consecutive_limit,
            change_5d_pct=change_5d_pct,
        )

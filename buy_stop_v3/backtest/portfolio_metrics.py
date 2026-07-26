"""Atlas Trading Agent — 组合级回测指标

基于每日净值曲线计算，使用复利。
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PortfolioMetrics:
    """组合回测指标（基于每日 equity curve）"""
    total_return_pct: float = 0.0       # 总收益率 (复利)
    annual_return_pct: float = 0.0      # 年化收益率
    max_drawdown_pct: float = 0.0       # 最大回撤
    sharpe_ratio: float = 0.0           # 夏普比率
    volatility_pct: float = 0.0         # 年化波动率
    profit_factor: float = 0.0          # 盈亏比
    total_trades: int = 0               # 总交易次数
    win_rate: float = 0.0               # 胜率
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    max_consecutive_losses: int = 0

    def compute_from_equity_curve(self, equity_curve: list[dict],
                                    trades: Optional[list] = None,
                                    risk_free_rate: float = 0.02):
        """从每日 equity curve 计算所有指标

        equity_curve: [{"date": str, "total_equity": float}, ...]
            每日收盘后的总资产（含现金+持仓市值）
        """
        if len(equity_curve) < 2:
            return self

        initial = equity_curve[0]["total_equity"]
        final = equity_curve[-1]["total_equity"]

        # 总收益率（复利）
        self.total_return_pct = round((final - initial) / initial * 100, 2)

        # 日收益率序列
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["total_equity"]
            curr = equity_curve[i]["total_equity"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        if not daily_returns:
            return self

        n_days = len(daily_returns)
        avg_daily_return = sum(daily_returns) / n_days

        # 年化收益率: (1 + total_return)^(365/n_days) - 1
        self.annual_return_pct = round(
            ((1 + self.total_return_pct / 100) ** (365 / n_days) - 1) * 100, 2
        ) if n_days > 0 else 0.0

        # 最大回撤（基于权益曲线）
        peak = initial
        max_dd = 0.0
        for entry in equity_curve:
            eq = entry["total_equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown_pct = round(max_dd, 2)

        # 波动率（年化）
        variance = 0.0
        if n_days >= 2:
            variance = sum((r - avg_daily_return) ** 2 for r in daily_returns) / (n_days - 1)
        daily_vol = math.sqrt(variance) if variance > 0 else 0.0
        self.volatility_pct = round(daily_vol * math.sqrt(252) * 100, 2)

        # 夏普比率
        daily_rf = risk_free_rate / 252
        if self.volatility_pct > 0:
            excess_return = avg_daily_return - daily_rf
            self.sharpe_ratio = round(
                excess_return / daily_vol * math.sqrt(252), 2
            ) if daily_vol > 0 else 0.0

        # 交易统计（如有提供）
        if trades:
            self.total_trades = len(trades)
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            self.win_rate = round(len(wins) / len(trades) * 100, 1) if trades else 0
            self.avg_win_pct = round(sum(wins) / len(wins), 2) if wins else 0
            self.avg_loss_pct = round(sum(losses) / len(losses), 2) if losses else 0

            total_win = sum(wins)
            total_loss = abs(sum(losses))
            self.profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else float('inf')

            # 最大连续亏损
            streak = 0
            for t in trades:
                if t <= 0:
                    streak += 1
                    if streak > self.max_consecutive_losses:
                        self.max_consecutive_losses = streak
                else:
                    streak = 0

        return self

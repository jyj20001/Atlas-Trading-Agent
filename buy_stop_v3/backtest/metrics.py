"""
Buy Stop V3 — 回测指标计算
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TradeMetrics:
    """单笔交易指标"""
    pnl_pct: float              # 盈亏百分比（扣除成本后）
    pnl_amount: float           # 盈亏金额
    bars_held: int              # 持仓天数
    exit_reason: str            # stop_loss / take_profit / timeout
    signal_score: int           # 信号评分
    config: str = ""            # A/B/C/D


@dataclass
class BacktestMetrics:
    """回测汇总指标"""
    config: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl_pct: float = 0.0
    avg_pnl_pct: float = 0.0
    profit_factor: float = 0.0       # 盈亏比
    max_drawdown: float = 0.0        # 最大回撤%
    avg_bars_held: float = 0.0       # 平均持仓天数
    max_consecutive_losses: int = 0  # 最大连续亏损次数
    total_cost_pct: float = 0.0      # 总交易成本%

    # 分组统计
    score_groups: dict = field(default_factory=dict)

    def compute(self, trades: list[TradeMetrics], cost_per_trade_pct: float = 0.001):
        """从交易列表计算汇总指标"""
        n = len(trades)
        if n == 0:
            return self

        self.total_trades = n
        self.winning_trades = sum(1 for t in trades if t.pnl_pct > 0)
        self.losing_trades = sum(1 for t in trades if t.pnl_pct <= 0)
        self.win_rate = round(self.winning_trades / n * 100, 1)
        self.total_pnl_pct = round(sum(t.pnl_pct for t in trades), 2)
        self.avg_pnl_pct = round(self.total_pnl_pct / n, 2)
        self.avg_bars_held = round(sum(t.bars_held for t in trades) / n, 1)

        # 盈亏比
        total_win = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
        total_loss = abs(sum(t.pnl_pct for t in trades if t.pnl_pct <= 0))
        self.profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else float('inf')

        # 最大回撤（简化：逐笔累加权益）
        equity = 0.0
        peak = 0.0
        for t in trades:
            equity += t.pnl_pct
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > self.max_drawdown:
                self.max_drawdown = round(dd, 2)

        # 最大连续亏损
        streak = 0
        for t in trades:
            if t.pnl_pct <= 0:
                streak += 1
                if streak > self.max_consecutive_losses:
                    self.max_consecutive_losses = streak
            else:
                streak = 0

        # 总交易成本
        self.total_cost_pct = round(n * cost_per_trade_pct * 2, 2)

        # 按评分分组
        groups = {}
        for t in trades:
            bucket = (t.signal_score // 10) * 10
            groups.setdefault(bucket, []).append(t)
        self.score_groups = {
            f"{k}-{k+9}": {
                "trades": len(v),
                "win_rate": round(sum(1 for t in v if t.pnl_pct > 0) / len(v) * 100, 1),
                "avg_pnl": round(sum(t.pnl_pct for t in v) / len(v), 2),
            }
            for k, v in sorted(groups.items())
        }

        return self


def format_metrics(metrics: BacktestMetrics) -> str:
    """格式化输出为可读文本"""
    lines = []
    lines.append(f"配置 {metrics.config}:")
    lines.append(f"  交易次数: {metrics.total_trades}")
    lines.append(f"  胜率: {metrics.win_rate}%")
    lines.append(f"  平均收益: {metrics.avg_pnl_pct}%")
    lines.append(f"  总收益: {metrics.total_pnl_pct}%")
    lines.append(f"  盈亏比: {metrics.profit_factor}")
    lines.append(f"  最大回撤: {metrics.max_drawdown}%")
    lines.append(f"  平均持仓: {metrics.avg_bars_held}天")
    lines.append(f"  最大连续亏损: {metrics.max_consecutive_losses}次")
    lines.append(f"  总交易成本: {metrics.total_cost_pct}%")
    if metrics.score_groups:
        lines.append(f"  评分分组:")
        for bucket, stats in metrics.score_groups.items():
            lines.append(f"    {bucket}分: {stats['trades']}笔 "
                         f"胜率{stats['win_rate']}% "
                         f"均收益{stats['avg_pnl']}%")
    return "\n".join(lines)

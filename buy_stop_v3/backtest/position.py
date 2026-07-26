"""Atlas Trading Agent — 持仓数据结构"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    """单只股票的持仓"""
    code: str
    name: str
    entry_date: str           # 买入日期 YYYY-MM-DD
    entry_price: float         # 买入均价
    quantity: int              # 持仓股数（100 的整数倍）
    stop_loss: float           # 止损价
    target_price: float        # 止盈价
    current_price: float       # 最新价（每日更新）
    cost_basis: float          # 总成本（含佣金）
    market_value: float = 0.0  # 当前市值
    pnl_pct: float = 0.0       # 盈亏百分比
    max_hold_days: int = 30    # 最长持有天数
    entry_idx: int = 0         # 在 K 线中的索引位置

    def update_price(self, price: float):
        self.current_price = price
        self.market_value = round(self.quantity * price, 2)
        if self.cost_basis > 0:
            self.pnl_pct = round((self.market_value - self.cost_basis) / self.cost_basis * 100, 2)

    @property
    def should_stop(self) -> bool:
        return self.current_price <= self.stop_loss

    @property
    def should_take_profit(self) -> bool:
        return self.current_price >= self.target_price

    def is_expired(self, bars_held: int) -> bool:
        return bars_held >= self.max_hold_days

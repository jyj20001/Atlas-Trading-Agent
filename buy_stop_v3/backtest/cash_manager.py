"""Atlas Trading Agent — 资金管理（含 A 股 T+1 交收）"""


class CashManager:
    """资金账户管理（非 dataclass，使用自定义 __init__）

    A 股规则:
      - T+1 卖出: 当日卖出股票，资金次日可用
      - T+1 买入: 当日买入股票，资金当日冻结
    """

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = initial_capital
        self.available_cash = initial_capital
        self.frozen_cash = 0.0
        self.total_positions_value = 0.0
        self.total_cost_basis = 0.0

    @property
    def total_equity(self) -> float:
        """总资产 = 可用现金 + 持仓市值"""
        return self.available_cash + self.total_positions_value

    @property
    def total_assets(self) -> float:
        """总资产含冻结 = 可用现金 + 冻结资金 + 持仓市值"""
        return self.available_cash + self.frozen_cash + self.total_positions_value

    @property
    def position_ratio(self) -> float:
        """仓位比例"""
        if self.initial_capital == 0:
            return 0.0
        return round(self.total_positions_value / self.total_assets * 100, 2)

    def can_buy(self, amount: float) -> bool:
        """检查是否有足够资金买入"""
        return amount <= self.available_cash

    def buy(self, amount: float) -> bool:
        """买入：冻结可用资金"""
        if not self.can_buy(amount):
            return False
        self.available_cash -= amount
        self.total_cost_basis += amount
        return True

    def sell(self, proceeds: float, cost: float) -> float:
        """卖出：资金 T+1 到账（标记为冻结）
        
        返回本次卖出盈亏金额
        """
        pnl = proceeds - cost
        self.total_cost_basis -= cost
        self.total_positions_value -= cost  # 会被 update_position 修正
        self.frozen_cash += proceeds  # T+1 冻结
        return pnl

    def unfreeze_cash(self):
        """T+1 资金解冻（每日开盘前调用）"""
        self.available_cash += self.frozen_cash
        self.frozen_cash = 0.0

    def update_position_value(self, total_market_value: float):
        """更新持仓市值"""
        self.total_positions_value = total_market_value

    def daily_return_pct(self) -> float:
        """当日收益率 = (今日总资产 - 昨日总资产) / 昨日总资产"""
        # 调用者需在每日更新后保存前一日 equity
        return 0.0  # 由调用者计算

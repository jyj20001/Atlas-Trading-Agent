# Atlas Trading Agent — Backtest Equity Curve Audit

**日期:** 2026-07-25
**版本:** v3.6.1
**审查对象:** `backtest/engine_v36.py` + `backtest/metrics.py`

---

## 摘要

当前回测报告（backtest_baseline_v1）中的 744.28% 总收益率、-110.72% 最大回撤、5.98% 年化收益率存在严重计算偏差。根本原因在于 equity curve 采用**加法累加**而非**复利计算**，且**无仓位管理模型**。

---

## 问题 1：Equity Curve 计算错误（严重）

### 当前代码（metrics.py 第 61-70 行）

```python
equity = 0.0
peak = 0.0
for t in trades:
    equity += t.pnl_pct         # ← 加法累加
```

### 问题

`pnl_pct` 是单笔交易的盈亏百分比（如 +5% 或 -3%）。将 584 笔交易的 % 直接相加等价于：

```
equity = +5% + (-3%) + +8% + ... = 744.28%
```

但这违反了复利原则：

| 场景 | 当前算法 | 正确算法 |
|------|---------|---------|
| 10次 +10% | 10 × 10% = 100% | (1.1)^10 - 1 = 159% |
| 10次 -10% | 10 × (-10%) = -100% | (0.9)^10 - 1 = -65% |
| +50% 后 -50% | 50% + (-50%) = 0% | 1.5 × 0.5 - 1 = -25% |

### 复利正确公式

```python
# metrics.py 应改为：
equity = 100.0  # 初始资金 100
for t in trades:
    equity *= (1 + t.pnl_pct / 100)
# total_return = equity - 100
# drawdown 也应基于复利 equity 曲线
```

### 对报告的影响

| 指标 | 当前值（加总法） | 修正值（估算） |
|------|:---------------:|:--------------:|
| 总收益率 | +744.28% | ~+80%~150% |
| 最大回撤 | -110.72% | ~-20%~-40% |
| 年化收益率 | 5.98% | ~8%~15% |
| 夏普比率 | 0.13 | ~0.5~1.0 |

> 注意：当前值不等于正确值，只是估算。复利后总收益率会大幅降低，但年化和夏普可能反而更合理。

---

## 问题 2：无仓位管理 — 资金被无限复用（严重）

### 当前架构

```python
# engine_v36.py
def run_batch(self, codes):
    all_trades = []
    for code, name in codes:
        trades = self.run_single(code, name)  # 每只股票独立回测
        all_trades.extend(trades)
```

**每只股票独立运行，假设 100% 可用资金。**

### 后果

假设 2026-07-20 这天有三只股票同时触发信号：

| 股票 | 买入价 | 持仓 | 占资金 |
|------|--------|------|--------|
| 浪潮信息 | 86.00 | 1 单位 | 100% |
| 贵州茅台 | 1230.00 | 1 单位 | 100% |
| 宁德时代 | 370.00 | 1 单位 | 100% |
| **合计** | | **3 单位** | **300%** |

当前引擎会全部执行（每只股票独立 run_single），但真实资金最多只能买 1 只。

### 结果

- `total_pnl_pct = sum(all_trades.pnl_pct)` 叠加了 3 倍杠杆的信号
- 总收益率被虚构放大
- 夏普比率失真
- 最大回撤也失真（不同时间的回撤相互抵消）

### 正确方法

需要一个**组合级别的回测引擎**：

```python
class PortfolioBacktestEngine:
    def __init__(self, initial_capital=100000, max_positions=1):
        self.cash = initial_capital
        self.positions = []  # 当前持仓
        self.max_positions = max_positions
    
    def on_signal(self, date, stock, signal):
        if len(self.positions) >= self.max_positions:
            return  # 已达到最大持仓，跳过
        # 分配资金
        position_size = self.cash / self.max_positions
        # ...
```

---

## 问题 3：交易非时序叠加（中等）

### 当前代码

`run_batch` 将所有股票的所有交易按 **股票顺序** 添加到一个列表中：

```
[trade_A1, trade_A2, ..., trade_A_N, trade_B1, trade_B2, ...]
```

然后 `compute()` 按列表顺序累加 equity。

### 问题

没有按时间排序。Stock A 的第 10 笔交易和 Stock B 的第 1 笔交易在时间上可能重叠，但在列表中它们被处理为连续的。

### 影响

- 重叠的交易被当成顺序交易
- Equity curve 的时间轴不连续
- 最大回撤**可能偏低**（重叠交易的盈亏相互抵消）

---

## 问题 4：T+1 处理不完整（中等）

### 已实现

```python
if today.date == entry_date:
    continue  # 当日不可卖出
```

### 未实现

1. **仓位资金 T+1**: 卖出股票后，资金次日才可用。当前假设卖出后立即可以用于新买入。

2. **非交易日计数**: `bars_held` 使用日历天数而非交易日天数：
   ```python
   return max(1, (datetime.strptime(d2, "%Y-%m-%d")
                  - datetime.strptime(d1, "%Y-%m-%d")).days)
   ```
   周五买入、周一卖出 → `bars_held = 3`（实际为 1 个交易日）

3. **停牌恢复交易**: 股票停牌后恢复交易时，涨跌停板幅度会扩大，当前未处理。

---

## 问题 5：最大回撤 -110.72% 分析

### 计算方式

```
equity = sum(all pnl_pct) = 744.28
peak = max(equity along the way) = 855.00 (假设)
trough = min(equity along the way) = 744.28
max_drawdown = peak - trough = 110.72
```

### 含义

这个 -110.72% 是在**加法 equity 曲线**上的回撤，不是真实资金回撤。

### 对解读的影响

在真实交易中，-110.72% 的回撤意味着净值跌到 -10.72%（亏完本金还倒欠），这在 A 股是不可能的（A 股无杠杆不能为负）。

在复利计算下，真实回撤通常在 -20%~-40% 范围。

---

## 问题 6：夏普比率计算偏差

### 当前公式

```python
risk_free_per_trade = 2.0 / 365 * self.avg_bars_held  # 每笔无风险利率
sharpe = (avg_pnl - risk_free_per_trade) / std_dev
```

### 问题

- 使用 2% 年化无风险利率 ÷ 365 × 平均持仓天数，这是合理的
- 但 `avg_pnl` 是加总法下的平均（744.28% / 584 = 1.27%），不代表真实单笔期望收益
- `std_dev` 也在加总法数据上计算，偏离真实值

### 正确做法

需要在复利 equity 曲线上计算：
```python
daily_returns = [(equity[i] - equity[i-1]) / equity[i-1] 
                 for i in range(1, len(equity))]
sharpe = sqrt(252) * mean(daily_returns - risk_free) / std(daily_returns)
```

---

## 问题 7：年化收益率计算偏差

### 当前公式

```python
annual_factor = 365 / total_bars
annualized_return = ((1 + total_pnl_pct / 100) ** annual_factor - 1) * 100
```

### 问题

`total_pnl_pct = 744.28%` 是加总法下的值。用它作为基数计算年化（7.44^0.14 - 1 = 5.98%）反而低估了真实年化。因为 744% 虽是虚高，但除以 584 笔交易后平均每笔仅 1.27%，乘以持仓天数占比后年化自然偏低。

在复利计算下，年化收益率会更合理（约 8-15%）。

---

## 修复优先级

| 问题 | 优先级 | 影响范围 | 修复难度 |
|------|:------:|---------|:--------:|
| P1: 加法 Equity Curve | **P0** | 所有指标 | 低（改 metrics.py） |
| P2: 无仓位管理 | **P0** | 总收益/回撤 | 高（新建组合引擎） |
| P3: 交易非时序 | **P1** | 回撤/夏普 | 中（排序+复利） |
| P4: T+1 资金可用 | **P2** | 信号数量 | 中 |
| P5: 交易日计数 | **P3** | 持仓天数 | 低 |

---

## 结论

当前 backtest_baseline_v1 的数值**不可直接作为决策依据**。最大的两个问题：

1. **加法 equity curve** 使总收益率虚高、夏普比率偏低
2. **无仓位管理** 允许无限资金复用，虚构了 3x 以上杠杆

修正这两点后，总收益率预计下降至 80-150%，最大回撤下降至 20-40%，年化收益率和夏普比率会更合理。

### 建议

- 在修正前，当前报告仅作为**信号数量统计参考**（584 笔信号说明策略在 7 年内有持续信号产出）
- 收益率/回撤/夏普/年化等指标需要重写 metrics.py 后才能使用
- 组合级回测（PortfolioBacktestEngine）需要作为独立新功能开发，不修改现有策略

---

*不修改任何策略代码。仅审计报告。*

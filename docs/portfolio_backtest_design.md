# Atlas Trading Agent — Portfolio Backtest Engine 设计文档

**版本:** 1.0.0
**日期:** 2026-07-25

---

## 1. 架构概览

```
┌────────────────────────────────────────────────────┐
│                  PortfolioEngine                     │
│  (时间驱动组合回测引擎)                               │
├────────────────────────────────────────────────────┤
│                      │                              │
│         ┌────────────┼────────────┐                 │
│         ▼            ▼            ▼                 │
│  SignalCollector  CashManager  Position             │
│  (信号预生成)      (资金管理)    (持仓管理)          │
│         │            │            │                 │
│         └────────────┼────────────┘                 │
│                      ▼                              │
│            PortfolioMetrics                         │
│            (组合指标-复利)                           │
└────────────────────────────────────────────────────┘
```

## 2. 文件结构

| 文件 | 职责 |
|------|------|
| `backtest/signal_collector.py` | 与 engine_v36 使用相同 Screener 预生成信号 |
| `backtest/cash_manager.py` | A 股资金账户管理（T+1 交收） |
| `backtest/position.py` | 单只持仓数据结构 |
| `backtest/portfolio_engine.py` | 时间驱动组合回测引擎 |
| `backtest/portfolio_metrics.py` | 复利指标计算（含夏普/年化/回撤） |

## 3. 核心改进

### 3.1 从加总法到复利法

| 项目 | engine_v36 (旧) | PortfolioEngine (新) |
|------|----------------|---------------------|
| 收益率 | `sum(pnl_pct)` 加总 | `(equity_end / equity_start) - 1` 复利 |
| Equity curve | 无 daily 曲线 | 每日记录 cash/market_value/equity |
| 回撤 | 基于加总 equity | 基于复利 equity 曲线峰值回撤 |
| 夏普比率 | 基于加总 pnl 统计 | 基于日收益率序列 × sqrt(252) |
| 年化收益 | `(1+total_pnl)^(365/bars) - 1` | `(1+total_return)^(365/days) - 1` |

### 3.2 从独立回测到组合回测

| 项目 | engine_v36 (旧) | PortfolioEngine (新) |
|------|----------------|---------------------|
| 资金 | 无限制（每只股票独立 100% 资金） | 统一资金池，可用 ≥ 买入金额 |
| 持仓 | 单只股票（独立状态机） | 最多 5 只同时持仓 |
| 仓位 | 100% 每笔 | 单股票 ≤ 20% 总资产 |
| 信号 | 即时执行 | 按日期排序 + 资金/仓位检查 |
| 时间轴 | 每只股票独立 | 所有信号按 signal_date 统一排序 |

### 3.3 A 股规则实现

| 规则 | 实现 |
|------|------|
| **T+1 卖出** | `entry_date == today` 时跳过退出检查 |
| **T+1 资金** | 卖出金额放入 `frozen_cash`，次日 `unfreeze` 后进入 `available_cash` |
| **涨停无法买入** | 突破价 ≥ 涨停价时跳过 |
| **一字涨停** | 开盘涨停且成交量 < 10 万股时跳过 |
| **跌停无法卖出** | 止损日检查跌停，锁仓至可卖日 |
| **开盘跳空** | 成交价 = max(bp, 开盘) × (1 + 滑点) |
| **以手为单位** | quantity = floor(金额 / 股价 / 100) × 100 |
| **最小交易额** | 单笔 ≥ 10,000 元 |

## 4. 数据流

### 4.1 信号预生成

```
collect_signals(codes, start_date, end_date, config="D")
  ├── for each stock:
  │     for each day (warmup → end):
  │       ├── StockScreener.evaluate(klines, snapshot)
  │       └── if passed → record Signal{date, code, bp, sl, target, score}
  └── sort all signals by date
  └── return list[Signal]
```

### 4.2 组合运行

```
PortfolioEngine.run(signals)
  ├── group signals by date
  ├── for each date (sorted):
  │     ├── 1. T+1 unfreeze
  │     ├── 2. Update all positions' prices
  │     ├── 3. Process exits (stop/take/timeout)
  │     ├── 4. Try to fill new signals (sorted by score desc)
  │     │     ├── check cash: must have enough
  │     │     ├── check max positions: ≤ 5
  │     │     ├── check position size: ≤ 20% of total
  │     │     └── if all pass → execute buy
  │     └── 5. Record daily snapshot
  ├── liquidate all on last day
  └── PortfolioMetrics.compute(equity_curve)
```

## 5. 指标计算公式

### 总收益率（复利）
```
total_return = (final_equity / initial_equity) - 1
```

### 年化收益率
```
annual_return = (1 + total_return) ^ (365 / total_days) - 1
```

### 最大回撤
```
drawdown_i = (peak_i - equity_i) / peak_i
max_drawdown = max(drawdown_i for all i)
```

### 夏普比率
```
daily_returns = [(e_t - e_t-1) / e_t-1 for each day]
sharpe = sqrt(252) × mean(daily_returns - risk_free / 252) / std(daily_returns)
```

### 年化波动率
```
volatility = std(daily_returns) × sqrt(252)
```

## 6. 约束参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `initial_capital` | 1,000,000 | 初始资金 |
| `max_position_pct` | 20% | 单股票最大仓位 |
| `max_positions` | 5 | 最大同时持仓数 |
| `max_hold_days` | 30 | 最长持有天数 |
| `commission_rate` | 0.025% | 佣金 |
| `stamp_tax_rate` | 0.1% | 印花税（卖出） |
| `slippage_rate` | 0.1% | 滑点 |
| `lot_size` | 100 | A 股每手股数 |
| `min_trade_amount` | 10,000 | 最小交易金额 |

## 7. 与现有系统的关系

### 可复用
- `engine_v36.py` → `_limit_pct`, `_is_limit_down`, `_calc_limit_price`
- `engine_v36.py` → `_generate_signal` 逻辑（在 `signal_collector.py` 中内联）
- `context.py` → `BacktestContext`（信号生成时注入 snapshot 数据）

### 不修改
- `core/screener.py` — 未修改
- `core/fundamental_scorer.py` — 未修改
- `core/sector_scorer.py` — 未修改
- `engine_v36.py` — 未修改
- 130 分评分体系 — 未修改
- Buy Stop 策略 — 未修改

### 新增独立
- `backtest/signal_collector.py` — 信号预生成
- `backtest/cash_manager.py` — 资金管理
- `backtest/position.py` — 持仓模型
- `backtest/portfolio_engine.py` — 组合引擎
- `backtest/portfolio_metrics.py` — 组合指标

## 8. 测试覆盖

| 测试 | 断言 | 说明 |
|------|:----:|------|
| CashManager 基础 | 9 | 买入/卖出/T+1 冻结解冻 |
| 同日资金不足 | 3 | 信号多但资金有限，仅部分可买 |
| T+1 资金冻结 | 4 | 冻结期间不可用，解冻后可买 |
| 仓位限制 20% | 3 | 不超过总资产 20% |
| 复利指标 | 3 | 复利总收益/回撤/夏普计算正确 |
| 完整流程 | 2 | 引擎运行完成/净值曲线非空 |
| **合计** | **24** | **6/6 通过** |

## 9. 与旧引擎的差异对比

| 指标 | engine_v36 (旧) | PortfolioEngine (新) |
|------|:---------------:|:--------------------:|
| 总收益率算法 | `sum(pnl_pct)` 加总 | `equity_end/equity_start - 1` 复利 |
| 仓位管理 | 每只股票 100% 独立 | 统一资金池，单票 ≤20%，最多 5 只 |
| 资金复用 | 无限（虚构 3x~5x 杠杆） | 受资金约束 |
| T+1 资金 | 未实现 | 卖出资金冻结至次日 |
| 日净值曲线 | 无 | 有（CSV 输出） |
| 最大回撤 | 基于加总（-110%） | 基于复利 equity 曲线 |
| 夏普比率 | 基于单笔 pnl | 基于日收益率 × sqrt(252) |
| 年化收益率 | 基于加总收益 | 基于复利总收益 |
| 信号数量参考 | 可用 | 可用（因筛选逻辑相同） |
| 收益率参考 | 不可用（严重虚高） | 可用 |

---

*等待人工审核，不进行参数优化。*

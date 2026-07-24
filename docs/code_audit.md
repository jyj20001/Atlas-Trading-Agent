# 工程体检报告

> 生成日期：2026-07-24
> 范围：buy_stop_v3/ 全部 Python 源代码文件

---

## 1. 死代码

| 文件 | 行 | 问题 | 严重度 |
|------|:--:|------|:------:|
| `core/__init__.py` | 6 | 导入了 `merge_fundamental_score` 但从未在外部调用 | ⚠️ 低 |
| `main.py` | 全文件 | 占位入口，只打印一条消息，从未被实际使用 | ⚠️ 低 |
| `data/market_fetcher.py` | 253-262 | `to_screener_input` 函数（import via lazy）在 `test_market_fetcher.py:263` 被导入但仅在测试中使用 | ⚠️ 低 |
| `utils/wecom.py` | 全文件 | `push_text()`、`push_markdown()`、`push_scan_report()` 三个函数都标记为 TODO/预留，功能已被 `utils/notifier.py` 取代 | ⚠️ 低 |
| `data/market_fetcher.py` | 336-342 | `__main__` 中的演示代码通过 `from core.screener import StockScreener` 调用 StockScreener（间接依赖） | ✅ 可接受（仅 __main__） |

**建议：** `main.py` 可以删除。`utils/wecom.py` 可以标记为已弃用。`core/__init__.py` 中未使用的导出可以清理。

---

## 2. 重复代码

| 位置 | 重复内容 | 详细 |
|------|---------|------|
| `scanner/batch_runner.py:107-148` | `_prefilter()` 中的连续涨停检测 | 与 `core/screener.py:306-358` 的 `_risk_flagger` 中的连续涨停检测逻辑高度相似。预过滤先跑一次（仅检查 >= 3），screener 中再跑一次完整版。 |
| `core/market_regime.py:147-158` | 5日涨跌计算 | `_change_5d` 与 `core/sector_scorer.py:212-225` 的 `_stock_return_5d` 功能重复。两者都从K线计算5日涨跌幅。 |
| `core/screener.py:263-267` | 距突破天数计算 | 与 `core/breakout_stage.py:75-81` 的距突破天数计算逻辑重复。 |
| `data/market_fetcher.py` | 多个数据格式兼容代码 | 多个函数重复使用类似的 dict/tuple/object 兼容性解析（如 `_get_close` 模式） |

**建议：** 放量预过滤和 screener 中的完整版连续涨停检测是不同层级的设计，保留。距突破天数计算可为两个调用点共享一个工具函数。5日涨跌计算可抽取为工具函数。

---

## 3. 无调用或未被引用的模块/函数

| 文件 | 函数/类 | 未被引用处 |
|------|---------|-----------|
| `utils/wecom.py` | 3 个函数 | 无外部调用（所有推送都走 `utils/notifier.py`） |
| `backtest/__init__.py` | 导出的全部 | `test_notifier.py:29` 从 `scanner` 而非 `backtest` 导入。`backtest` 仅被 test 文件和直接调用。 |
| `utils/helpers.py:76-77` | `today_str()` | 无外部调用（始终用 `date.today().isoformat()` 内联） |
| `scanner/universe.py:90-101` | `_is_listed_long_enough` | 简化版直接返回 True（已是死代码） |
| `data/types.py:87-94` | `ScreenerResult` | 仅在 `core/screener.py:515-546` 的 `run_screener()` 中使用，而 `run_screener()` 未被 `scanner/batch_runner.py` 调用（batch_runner 使用直接评估） |

---

## 4. 命名不一致

| 问题 | 示例 |
|------|------|
| 中英混合文档注释 | 部分文件纯英文、部分纯中文、部分中英混合 |
| 变量命名风格不一致 | 有 `camelCase`（如 `days_since_breakout` + `consecutive_limit`）、`snake_case`（绝大部分） |
| 常量命名 | `_PUSH_SCORE_MIN`（大写+下划线）✓ 部分模块没有使用 ALL_CAPS 常量命名 |
| 模块导出风格 | `core/__init__.py` 显式导出，`utils/__init__.py` 为空，`scanner/__init__.py` 导出不一致 |

**建议：** 不影响运行的命名风格问题，优先级较低。迁移后可统一使用 ruff 格式化。

---

## 5. 可以优化但不影响稳定性的地方

| 区域 | 描述 | 预期收益 |
|------|------|---------|
| 缓存机制 | `utils/helpers.py` 的文件缓存（JSON 文件）可考虑使用 SQLite | 减少 IO 和序列化开销 |
| 板块评分 | `core/sector_scorer.py:26-73` 的板块代码映射表只有 30+ 板块，可通过自动获取扩展 | 更好的板块覆盖 |
| HTTP 客户端 | `get_json` 的 `_raw_text` 参数使返回类型不一致（str vs dict） | 类型安全性 |
| 市场环境 | `MarketRegimeScorer.fetch_index_klines` 返回 dict 列表而非 KLine 对象 | 不必强制兼容 3 种数据格式 |
| 日志轮换 | `logger.py:39` 的 `fh.namer` 覆盖可能导致文件名偏差 | 日志管理一致性 |
| 测试 import | 多个测试文件使用 `sys.path.insert(0, "")` 或 `from tests/` 外的相对导入 | 使用 pytest 时可以清理 |
| test_screener_fundamental.py | 使用 `_scr_mod.BreakoutStage` 的动态修改 | 不必要的复杂性 |

---

## 6. 潜在风险

| 风险 | 描述 | 影响 |
|------|------|------|
| 新浪 API 返回格式 | 新浪财经返回 JSON 可能以非标准格式（如不在 _list 字段） | 股票列表获取可能失败 |
| curl 路径 | hardcoded `curl` 依赖系统 PATH | 某些系统需要指定绝对路径 |
| 巨潮资讯反爬 | 频繁请求可能被封 IP | 基本面评分失效 |
| 连续涨停预过滤重复 | batch_runner 中 `_prefilter` 过滤后，screener 中 `_risk_flagger` 再跑一次 | 逻辑冗余但不是 bug |

**建议：** 以上风险可控。最需要关注的是数据源变更风险（新浪/腾讯/巨潮）。

---

## 总结

| 类别 | 数量 | 优先级 |
|------|:----:|:------:|
| 死代码 | 3 处 | ⚠️ 低 |
| 重复代码 | 4 处 | ⚠️ 低 |
| 未调用函数 | 4 处 | ✅ 无影响 |
| 命名不一致 | 少量 | ✅ 低优先级 |
| 可优化点 | 7 处 | ✅ 低优先级 |
| 潜在风险 | 4 个 | ⚠️ 需监控 |

**总体结论：** Buy Stop V3.4 代码质量良好，没有影响生产运行的问题。绝大部分"问题"是设计选择和可接受的工程权衡。本次体检未发现需要紧急处理的项。

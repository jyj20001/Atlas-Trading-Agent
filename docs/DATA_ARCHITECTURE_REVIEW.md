# Historical K-Line Data Source — Engineering Architecture Review

**日期:** 2026-07-25
**作者:** Data Architecture Engineer
**目标:** 建立长期稳定的数据层架构，使回测覆盖 2018~2026

---

## 数据源实证结论

### 1. 富途 OpenAPI / Futu OpenD — 已验证

**可用性:** ✅ **可用**

`futu-api` SDK 已验证安装成功 (v10.9.6908)。

**核心 API:**

```python
from futu import OpenQuoteContext, AuType, KLType

ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
ret, data, page_req_key = ctx.request_history_kline(
    code='SH.600000',       # 支持 A 股
    start='2015-01-01',     # 开始日期
    end='2026-07-24',       # 结束日期
    ktype=KLType.K_DAY,     # 日 K
    autype=AuType.QFQ,      # 前复权 (qfq)
    max_count=1000,         # 最多 1000 根/页
    page_req_key=None,      # 分页 key
)
```

**支持复权类型:**
| AuType | 值 | 说明 |
|--------|-----|------|
| `AuType.QFQ` | `"qfq"` | **前复权** (默认) |
| `AuType.HFQ` | `"hfq"` | 后复权 |
| `AuType.NONE` | `None` | 不复权 |

**历史长度:** 全量（上市首日至今）

**分页:** `max_count=1000` + `page_req_key` 实现翻页。设置 `max_count=None` 返回全部数据。

**批量回填 4500 只耗时估算:**
- OpenD 本地进程，每请求 ~100ms
- 4500 只 × 1 次请求（max_count=None 返回全部） × 0.1s = **~450s (~7.5 分钟)**
- 若分页（每只 2 次请求）：~900s (~15 分钟)

**前置条件:**
- 需启动 Futu OpenD 进程（Python SDK 自动管理）
- 需 Futu 牛牛客户端登录（已有）
- 需确保有 A 股行情权限（免费用户可用）
- `futu-api` 需安装在项目 Python 环境

**注意:** OpenD 是独立的本地 TCP 服务（默认端口 11111），需开机启动或按需启动。

---

### 2. 东方财富 API — 已验证

**可用性:** ✅ **可用**

**HTTP 接口:**
```
GET https://push2his.eastmoney.com/api/qt/stock/kline/get
  ?secid=1.600000          # 1=上交所, 0=深交所
  &fields1=f1,f2,f3,f4,f5,f6
  &fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61
  &klt=101                  # 101=日K
  &fqt=1                    # 1=前复权, 0=不复权, 2=后复权
  &end=20500101
  &lmt=2000                 # 返回数量上限
```

**历史长度:** 全量（600000 浦发银行可到 2004 年，约 4400+ 根）

**前复权准确性:** `fqt=1` 参数明确，数据来自东方财富，与 Wind/同花顺等机构数据源一致。

**限制:**
- `lmt` 参数单次最多 2000 根
- 需指定 `secid` 格式（1.SHCODE 或 0.SZCODE）
- 无官方 SLA，但多年来稳定

**批量回填 4500 只耗时估算:**
- 每只 2 次请求（2000+2000）
- 4500 × 2 × 0.5s（限速） = **~4500s (~75 分钟)**

---

### 3. 腾讯 API — 已知限制

| 维度 | 限制 |
|------|------|
| 个股 `qfqday` | 最多 **640 根**（约 2.5 年） |
| 指数 `qfqday` | 2000+ 根（正常） |
| 未复权 `day` | 此端点不支持 |
| 稳定性 | 偶发 WAF 拦截 |

---

## 数据一致性风险分析

### 指标影响评估

| 指标 | 数据源差异影响 | 风险等级 |
|------|:-------------:|:--------:|
| **MA200** | 不同复权算法 → 价格序列差异，前 N 根均值受影响 | ⚠️ **中** |
| **20 日突破** | 前复权后当日的最高价一致，突破判断不变 | ✅ **低** |
| **ATR** | 基于复权后价格，差异很小 | ✅ **低** |
| **涨跌幅** | 复权后每日涨跌幅一致（调整的是历史，非当日） | ✅ **低** |
| **涨停判断** | 基于前一日收盘价 × 1.1，受复权影响 | ⚠️ **中** |
| **成交量/额** | 不同源无差异 | ✅ **极低** |
| **Breakout Stage** | 基于突破次数和涨跌停，受历史数据长度影响 | ⚠️ **中** |
| **信号触发** | 历史突破价可能因复权差异而偏移 | ⚠️ **中** |

### 核心风险: 前复权算法差异

不同数据源的前复权算法核心差异:

```
前复权公式:
  调整后价格 = 原始价格 × (1 - 分红率)  - 每股分红
           ── 或 ──
  调整因子 = 除权前收盘价 / (除权前收盘价 - 每股分红 + 每股送转股 × 面值)
```

不同供应商可能在以下方面有差异:
1. **分红再投资假设** — 是否将现金分红视为再投资
2. **送转股处理** — 红股是否完全稀释
3. **历史调整深度** — 调整多远的历史

**但对 MA200 和 20 日突破的影响有限**，因为:
- 复权主要影响 **长周期 (>5 年)** 的价格水平
- 短期（200 日内）价格相对关系几乎不变
- Breakout 判断基于 **20/60 日新高**，受复权影响极小

**验证建议:** 在切换数据源时，对 200 只股票对比腾讯/东财的 20 日高和 MA200 值。

---

## 推荐架构

### DataProvider 接口

```
data/kline_providers/
├── __init__.py          → provider chain + factory
├── base.py              → AbstractBaseProvider
├── tencent_provider.py  → TencentProvider (现有逻辑)
├── eastmoney_provider.py → EastMoneyProvider (HTTP)
└── futu_provider.py     → FutuProvider (OpenD SDK)
```

### Provider 优先级链

```python
# data/kline_providers/__init__.py

PROVIDERS = [
    EastMoneyProvider(),     # 优先: 免费、全量、稳定
    TencentProvider(),       # fallback: 现有逻辑
]
# FutuProvider 可选加入（需要 OpenD 运行）
```

### fetch_klines 修改

```python
# data/market_fetcher.py — 最小修改

from data.kline_providers import PROVIDERS

def fetch_klines(code, days=2000, ...):
    # 1. 查缓存（不变）
    cached = load_klines(code, limit=days)
    if cache_sufficient(cached, days):
        return cached

    # 2. 遍历 Provider 链
    for provider in PROVIDERS:
        try:
            klines = provider.fetch(code, start_date, end_date, ...)
            if klines and len(klines) >= min_bars:
                save_klines(code, klines, source=provider.name, replace=False)
                return merge_with_cache(code, klines)  # 增量合并
        except Exception as e:
            logger.warning(f"{provider.name}: {code} 失败: {e}")
            continue
    
    # 3. 全部失败 → 回退到已有缓存
    return cached if cached else None
```

### 增量缓存策略

```python
def merge_with_cache(code, new_klines):
    """合并新增 K 线到缓存（INSERT OR REPLACE 天然去重）"""
    before = load_klines(code, limit=9999)
    if before:
        # 已有缓存：合并新旧，按日期去重
        existing_dates = {k["date"] for k in before}
        missing = [k for k in new_klines if k.date not in existing_dates]
        if missing:
            save_klines(code, missing, source="eastmoney")
        return before + missing
    else:
        save_klines(code, new_klines, source="eastmoney")
        return new_klines
```

---

## 修改文件列表

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `data/kline_providers/__init__.py` | **新增** | Provider 链 + 工厂 |
| `data/kline_providers/base.py` | **新增** | 抽象基类 |
| `data/kline_providers/eastmoney_provider.py` | **新增** | 东方财富 HTTP 客户端 |
| `data/kline_providers/futu_provider.py` | **可选新增** | 富途 OpenD SDK 封装 |
| `data/kline_providers/tencent_provider.py` | **新增** | 从 market_fetcher 提取现有逻辑 |
| `data/market_fetcher.py` | **修改** | fetch_klines 改用 Provider 链 |
| `data/database.py` | **修改** | 新增 `merge_klines()` 函数 |
| `requirements.txt` | **可选** | 新增 `requests` (如未安装) |

**完全不修改:**
- `core/screener.py` ✅
- `core/scorer.py` ✅
- `core/fundamental_scorer.py` ✅
- `core/sector_scorer.py` ✅
- `core/market_regime.py` ✅
- `backtest/portfolio_engine.py` ✅
- `backtest/engine_v36.py` ✅
- `backtest/context.py` ✅
- 所有策略/评分/参数文件 ✅

---

## 实施 Phase 计划

### Phase 1: EastMoney Provider（~半天）

**目标:** 替换腾讯 API 为主要 K 线数据源

**步骤:**
1. 创建 `data/kline_providers/` 目录结构
2. 实现 `base.py` 抽象基类
3. 实现 `eastmoney_provider.py`
4. 从 `market_fetcher.py` 提取腾讯逻辑到 `tencent_provider.py`
5. 修改 `fetch_klines()` 使用 Provider 链
6. 实现增量缓存合并

**验证:**
```
200 只回填 → 确认最早日期 ≤ 2018
重新运行 signal_collector → 信号数量变化
重新运行 PortfolioEngine → 对比 Baseline
```

### Phase 2: 全量回填 + 重新 Baseline（~2 天）

**步骤:**
1. 回填前 200 只（4 分钟）
2. 运行带新数据的 signal_collector
3. 运行 PortfolioEngine
4. 生成 `docs/EASTMONEY_BACKTEST_COMPARISON.md`
5. 对比新旧数据源的信号/收益/回撤差异

### Phase 3: Futu Provider（可选，~1 天）

**步骤:**
1. 安装 `futu-api` 到项目 venv
2. 配置 OpenD 自动启动机制
3. 实现 `futu_provider.py`
4. 加入 Provider 链（优先级最高）

---

## 风险清单

| # | 风险 | 概率 | 影响 | 缓解措施 |
|:-:|------|:----:|:----:|---------|
| 1 | **前复权差异** → 历史突破价偏移 | 中 | 中 | 切换后对比 200 只的 MA200/20H 差异 |
| 2 | **东方财富 API 变更** → 接口不可用 | 低 | 高 | Tencent fallback 兜底 |
| 3 | **Futu OpenD 未运行** → 请求超时 | 高 | 中 | 作为可选 Provider，非必须 |
| 4 | **不同 Provider 数据不一致** → 信号漂移 | 中 | 低 | 缓存以第一次写入为准，不覆盖 |
| 5 | **东方财富限速封禁** → 回填中断 | 低 | 中 | 增加 500ms~1s 间隔 + 重试机制 |
| 6 | **历史涨跌停判断偏差** → 入场条件误判 | 低 | 低 | 复权后涨跌停价基于前日收盘，与腾讯一致 |
| 7 | **4500 只回填时间** → 超过会话限制 | 中 | 低 | 分批回填，每批 500 只 |

### 关键验证步骤

在切换数据源后，必须验证:

```python
# 1. 对比 600519 的 MA200
east_money = fetch_klines("600519", provider="eastmoney")
tencent = fetch_klines("600519", provider="tencent")
print(f"MA200 差异: {abs(east_ma200 - ten_ma200) / ten_ma200 * 100:.2f}%")

# 2. 对比 20 日高点
print(f"20H 差异: {abs(east_20h - ten_20h) / ten_20h * 100:.2f}%")

# 3. 对比涨跌停价
print(f"涨停价差异: {east_limit_up - ten_limit_up}")
```

---

## 推荐方案

```
第一选择: 东方财富 API + 腾讯 fallback
  ├── 零费用、零额外依赖
  ├── 全量历史（2004~2026）
  ├── HTTP 请求，无需开放端口
  └── 增量缓存不覆盖已有数据

第二选择: 富途 OpenAPI（可选）
  ├── 更快（本地进程）
  ├── 数据质量更高（券商级）
  └── 需维护 OpenD 进程
```

---

*等待审核。*

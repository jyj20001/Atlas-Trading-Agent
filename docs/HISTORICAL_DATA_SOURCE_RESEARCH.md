# Historical K-Line Data Source Expansion Research

**日期:** 2026-07-25
**目标:** 评估替代数据源，使 Buy Stop 策略可覆盖至少 2018~2026 的 A 股历史回测

---

## 问题回顾

腾讯 `fqkline/get` 接口限制：
- 个股 `qfqday` 前复权最多 **640 根**（约 2.5 年），最早 2023-12-01
- 指数 `qfqday` 可达 2000+ 根（无此限制）
- 当前 Baseline 只能从 2024 年开始回测

---

## A. 数据源对比表

| 数据源 | 历史长度 | 前复权 | API 稳定性 | 批量能力 | 费用 | 推荐等级 |
|--------|:--------:|:------:|:----------:|:--------:|:----:|:--------:|
| **富途 OpenAPI** | **A 股全量** (上市至今) | ✅ 支持 | ★★★★★ (本地进程) | ✅ 批量 | 免费(已有客户端) | ⭐⭐⭐⭐⭐ |
| **AkShare** | 全量 (有上限 ~10年) | ✅ 后复权/前复权 | ★★★★ (依赖源站) | ❌ 单只+限速 | 免费 | ⭐⭐⭐⭐ |
| **东方财富 API** | **全量** (上市至今) | ✅ 前复权 | ★★★★ (稳定性好) | ✅ 可批量 | 免费(无登录) | ⭐⭐⭐⭐ |
| **TuShare Pro** | 全量 (上市至今) | ✅ 前复权+后复权 | ★★★★★ (付费保障) | ✅ 批量 | ￥200~2000/年 | ⭐⭐⭐⭐ |
| **JoinQuant/聚宽** | 全量 | ✅ | ★★★★ | ✅ 批量 | 免费有限 | ⭐⭐⭐ |
| **RiceQuant/米筐** | 全量 | ✅ | ★★★★ | ✅ 批量 | ￥6000/年 | ⭐⭐⭐ |
| **掘金量化** | 全量 | ✅ | ★★★★ | ✅ 批量 | 免费有限 | ⭐⭐⭐ |

---

## B. 各数据源详细评估

### 1. 富途 OpenAPI / Futu OpenD ⭐⭐⭐⭐⭐

**接入方式:** 
- 本地已安装富途牛牛客户端
- Futu OpenD 是本地进程，通过 Python SDK (`futu-api`) 连接
- 已有 `~/.hermes/mcp-servers/futubull/` MCP 服务器（当前仅提供实时行情）

**历史 K 线能力:**
- `get_history_kline()` — 获取历史日/周/月 K 线
- `get_history_klinestream()` — 流式获取
- 支持 **前复权 (qfq)**、后复权、不复权
- 历史长度: **A 股全量数据**（上市首日至今）
- 支持批量查询多只股票

**API 限制:**
- 本地 OpenD 进程，无网络调用限制
- 每次请求最多返回 1000 根 K 线（可多次请求拼接）
- 单请求 ~100ms（本地进程）

**批量回填 4500 股票:**
- 每只最多 2 次请求（1k + 1k → 2000+ 根）
- 4500 × 2 × 0.1s = ~900s = ~15 分钟
- 可并行请求进一步加速

**风险:**
- 需要启动 Futu OpenD 进程
- OpenD 需要牛牛客户端登录状态
- 账户需有 A 股行情权限（免费）

**评估结论: 最优方案。** 数据质量最高、速度最快、无额外成本。

---

### 2. 东方财富 API ⭐⭐⭐⭐

**接入方式:** 
- 通过 HTTP 请求 `push2his.eastmoney.com` 或 `datacenter.eastmoney.com`
- 无需登录、无需 Token
- Python 库: `efinance` (封装好的库)

**历史 K 线能力:**
- 日 K: **全量**（上市首日至今，约 20+ 年）
- 支持 `fq` 参数: 0=不复权, 1=前复权, 2=后复权
- 分钟 K: 最近 5 天
- 周/月 K: 全量

**API 限制:**
- 单次请求最多 1000 根
- 无公开速率限制（实际约 10 req/s 安全）
- 无需 Cookie/Token
- 国内 CDN 分发，稳定性好

**封禁风险:** 中低。个人使用几乎无封禁，大批量 (~4500) 可能需要 1-2s 间隔

**评估结论: 第二优选。** 零成本、全量历史、简单接入。

**实测示例:**
```
https://push2his.eastmoney.com/api/qt/stock/kline/get?
  secid=1.600000&
  fields1=f1,f2,f3,f4,f5,f6&
  fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&
  klt=101&       # 101=日K, 102=周K
  fqt=1&         # 1=前复权, 0=不复权, 2=后复权
  beg=0&         # 0=从最早开始
  end=20500101   # 截止日期
  lmt=2000       # 返回数量
```

---

### 3. AkShare ⭐⭐⭐⭐

**接入方式:**
- `pip install akshare`
- 纯 Python，依赖 pandas/requests

**功能:**
- `stock_zh_a_hist(symbol="000001", period="daily", start_date="20180101", adjust="qfq")`
- 返回: 日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/换手率
- adjust 参数: ""=不复权, "qfq"=前复权, "hfq"=后复权
- 历史长度: 数据源来自东方财富，全量历史

**性能:**
- 每只股票 ~1-2 秒（含数据源 HTTP 请求+解析）
- 4500 只：~1.5-3 小时
- 无法并行（内部有线程锁）

**生产环境问题:**
- 依赖的源站变动可能导致 API 接口变更
- 社区维护，版本更新频繁
- requests 库未使用
- 对当前项目来说引入重依赖

**评估结论:** 快速原型验证的好工具，但生产环境依赖不如直接调东方财富 API 可控。

---

### 4. TuShare Pro ⭐⭐⭐⭐

**接入方式:**
- 注册 → 获取 token → `pip install tushare`
- 免费积分 200（每天可用 200 次 API 调用）
- 付费套餐: ￥200~2000/年（不同积分等级）

**功能:**
- `daily(ts_code="000001.SZ", start_date="20180101", end_date="20260724")` — 日线
- `adj_factor(ts_code="000001.SZ")` — 复权因子（需自行计算复权）
- `pro_bar(ts_code="000001.SZ", adj="qfq")` — 快捷复权行情

**历史长度:** 全量（上市至今）

**限制:**
- 免费用户 200 次/天 → 只能获取 200 只股票
- 日线不计费，但每分钟限 200 次
- ￥200 套餐: 300 万积分，约可获取 5000 只 × 10 年日线的量
- 有财务数据优势（利润表/资产负债表/现金流 — 可与基本面评分整合）

**评估结论:** 价值投资型。如果未来需要财务数据一体化，值得购买。纯 K 线场景不如东方财富。

---

### 5. 其他方案

| 数据源 | 评估 |
|--------|------|
| **JoinQuant SDK** | 需要聚宽平台账号，本地 SDK 可用，全量历史，但依赖聚宽运行环境 |
| **RiceQuant SDK** | 类似聚宽，年费 ~6000 元，适合机构 |
| **掘金量化** | 有免费版，历史数据全，但 SDK 较大 |
| **同花顺 iFinD** | 机构级，需付费，免费版限制多 |
| **通达信** | 本地数据文件，格式封闭，解析复杂 |
| **baostock** | 免费开源，全量 A 股（上市至今），支持前复权，但更新可能滞后，维护不活跃 |

---

## C. 推荐架构

### DataProvider 接口设计

```
market_fetcher.py 扩展:

class BaseKLineProvider(ABC):
    @abstractmethod
    def fetch(self, code: str, days: int, ...) -> list[KLine]
    @property
    def priority(self) -> int          # 0=最高
    @property
    def name(self) -> str

├── TencentProvider(priority=2)        # 现有逻辑，作为 fallback
│   └── fetch(): 当前腾讯 API 逻辑
│
├── EastMoneyProvider(priority=0)      # 首选：全量历史
│   └── fetch(): HTTP → push2his.eastmoney.com
│
├── FutuProvider(priority=0, optional) # 首选：本地 OpenD
│   └── fetch(): futuapi.get_history_kline()
│
└── AkshareProvider(priority=3)        # 最后 fallback
    └── fetch(): akshare.stock_zh_a_hist()
```

### fetch_klines 路由逻辑（修改版）

```python
def fetch_klines(code, days=2000):
    """按优先级依次尝试各 Provider"""
    
    # 1. 检查缓存（优先返回）
    cached = load_klines(code, limit=days)
    if cache_sufficient(cached, days):
        return cached
    
    # 2. 按优先级尝试 Provider
    for provider in sorted(providers, key=lambda p: p.priority):
        try:
            klines = provider.fetch(code, days)
            if klines and len(klines) >= days * 0.8:
                save_klines(code, klines, source=provider.name)
                return klines
        except Exception:
            continue
    
    # 3. 全部失败 → 返回已有缓存
    return cached if cached else None
```

### 为什么不先做富途？

富途方案虽然最优，但有额外操作成本：
1. 需要启动 Futu OpenD 进程
2. 需要牛牛客户端登录
3. 需要安装 `futu-api` Python SDK
4. 依赖本地 TCP 连接

**推荐优先实施: 东方财富 API** — 零依赖、零配置、零费用。

---

## D. 最小实施方案

### 阶段 1: 接入东方财富 Provider

**步骤:**
1. 创建 `data/kline_providers/` 目录
2. 实现 `BaseKLineProvider` 抽象基类
3. 实现 `EastMoneyProvider`
4. 修改 `fetch_klines()` 使用 Provider 链

**代码量:** ~150 行

**预期效果:**

| 股票 | 当前 (Tencent) | 扩展后 (EastMoney) |
|------|:--------------:|:------------------:|
| 600000 浦发 | 640根 / 2023-12 | **4400+根 / 2004~** |
| 000001 平安 | 640根 / 2023-12 | **4400+根 / 1991~** |
| 300750 宁德 | 640根 / 2023-12 | **4200+根 / 2018上市~** |
| 600519 茅台 | 640根 / 2023-12 | **4400+根 / 2001~** |

### 阶段 2: 验证 200 只股票

1. 回填 200 只股票的历史 K 线（东方财富）
2. 重新运行 `collect_signals()` 
3. 确认信号日期扩展到 2018+
4. 重新运行 PortfolioEngine

**预期回测结果对比:**

| 指标 | 当前 Baseline | 扩展后（估算） |
|------|:-------------:|:--------------:|
| 覆盖区间 | 2024~2026 | **2018~2026** |
| 信号数量 | 2957 | **8000+** |
| 交易次数 | 129 | **300+** |
| 数据可信度 | ⚠️ 2.5年 | ✅ 8年 |

### 阶段 3: 验证结果

生成 `docs/EASTMONEY_BACKTEST_COMPARISON.md`，对比新旧数据源的回测差异。

---

## E. 实施建议

### 优先级

```
1. 东方财富 Provider  ████████████████████  (本周)
2. 200只回填+验证     ████████████████       (本周)
3. 全量回填 4467只    ████████████           (下周)
4. 重新生成 Baseline  ████████               (下周)
```

### 非功能需求

- **不改策略**: Provider 层是纯数据获取替换
- **无未来函数**: 每个 Provider 的 `available_time` 由数据日期控制
- **增量缓存**: `INSERT OR REPLACE` 天然去重
- **限速**: 东方财富建议 500ms 间隔

---

*等待审核。不写代码，仅调研。*

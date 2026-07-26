<!-- markdownlint-disable MD033 MD041 -->
<h1 align="center">
  <img src="docs/logo.svg" alt="" width="48" /><br/>
  Atlas Trading Agent
</h1>

<p align="center">
  <strong>A股 Buy Stop 趋势突破自动扫描系统</strong><br />
  每日收盘后自动扫描全市场 A 股，识别符合 Buy Stop 条件的突破候选，<br />
  输出评分报告并推送企业微信。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0--stable-blue" alt="版本" />
  <img src="https://img.shields.io/badge/python-3.11%2B-green" alt="Python" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
  <img src="https://img.shields.io/badge/status-production-brightgreen" alt="Status" />
</p>

---

## 当前状态

| 属性 | 值 |
|------|-----|
| **Version** | v1.0.0 Stable Baseline |
| **Stage** | Production — Version Freeze |
| **Goal** | Portfolio Backtesting Infrastructure |
| **Strategy** | Frozen — Buy Stop core sealed |

> **v1.0.0 Stable Baseline Release** — Buy Stop 策略核心已冻结，PortfolioEngine 组合回测基础设施就绪。后续仅限数据层扩展和 Bug 修复。

---

## 目录

- [当前状态](#当前状态)
- [功能模块](#功能模块)
- [系统架构](#系统架构)
- [评分体系](#评分体系)
- [突破生命周期](#突破生命周期)
- [快速开始](#快速开始)
- [用法指南](#用法指南)
- [配置企业微信](#配置企业微信)
- [配置 Cron](#配置-cron)
- [项目目录说明](#项目目录说明)
- [技术栈](#技术栈)
- [开发指南](#开发指南)
- [测试](#测试)
- [Roadmap](#roadmap)
- [注意事项](#注意事项)
- [License](#license)

---

## 功能模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **筛选引擎** | `buy_stop_v3/core/screener.py` | 130分五维评分，Buy Stop 信号生成 |
| **行情获取** | `buy_stop_v3/data/market_fetcher.py` | Provider Chain 架构（Futu→东方财富→腾讯） |
| **历史行情 DB** | `buy_stop_v3/data/database.py` | SQLite 全量 K 线数据库，单数据源 |
| **K线 Provider 链** | `buy_stop_v3/data/kline_providers/` | Futu OpenAPI / 东方财富 / 腾讯 三层 fallback |
| **Futu OpenD** | `buy_stop_v3/data/kline_providers/futu_provider.py` | 全量 2006~2026 历史日 K（需 OpenD 进程） |
| **K线标准化** | `buy_stop_v3/data/kline_normalizer.py` | 统一输出格式 (code/date/OHLC/vol/amount) |
| **基本面数据** | `buy_stop_v3/data/cninfo_fetcher.py` | 巨潮资讯业绩预告/快报/公告 |
| **HTTP 客户端** | `buy_stop_v3/data/http_client.py` | curl 子进程，零第三方依赖 |
| **突破生命周期** | `buy_stop_v3/core/breakout_stage.py` | EARLY/TRENDING/EXTENDED/CLIMAX 四阶段识别 |
| **市场环境** | `buy_stop_v3/core/market_regime.py` | 沪深300/上证/创业板指数综合评估 |
| **板块强度** | `buy_stop_v3/core/sector_scorer.py` | 30+行业板块，个股超收益评分 |
| **基本面评分** | `buy_stop_v3/core/fundamental_scorer.py` | 预增/快报/合同/回购时间衰减评分 |
| **批量扫描** | `buy_stop_v3/scanner/batch_runner.py` | 全市场扫描，异常隔离，重试 |
| **组合回测引擎** | `buy_stop_v3/backtest/portfolio_engine.py` | 时间驱动组合回测，T+1 资金管理 |
| **股票池** | `buy_stop_v3/scanner/universe.py` | ST/北交所过滤，上市天数判断 |
| **报告生成** | `buy_stop_v3/scanner/report.py` | JSON + Markdown + CSV 输出 |
| **企业微信通知** | `buy_stop_v3/utils/notifier.py` | A+ 级推送详情 |
| **日志系统** | `buy_stop_v3/utils/logger.py` | 按日轮换，保留30天 |
| **风险监控** | `alibaba_risk_monitor/` | 法律/新闻/价格异常独立监控 |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        Atlas Trading Agent                        │
├──────────────────────────────────────────────────────────────────┤
│                         ┌──────────────┐                          │
│                         │  run_scan.py  │                          │
│                         │  run_daily.sh  │                         │
│                         └──────┬───────┘                          │
│                                │                                  │
│          ┌─────────────────────┼─────────────────────┐            │
│          ▼                     ▼                     ▼            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐     │
│  │   scanner/    │    │    core/     │    │      data/       │     │
│  │  · universe   │    │ · screener   │    │ · market_fetcher │     │
│  │  · batch_runner│   │ · scorer     │    │ · cninfo_fetcher │     │
│  │  · report     │    │ · market_regime│  │ · http_client    │     │
│  └──────────────┘    │ · sector_scorer│  │ · types          │     │
│                       │ · breakout_stage │ └──────────────────┘     │
│                       │ · fundamental   │                          │
│                       └──────────────┘                             │
│                                │                                  │
│          ┌─────────────────────┼─────────────────────┐            │
│          ▼                     ▼                     ▼            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐     │
│  │   backtest/   │    │   utils/     │    │ alibaba_risk_     │     │
│  │  · engine     │    │ · notifier   │    │   monitor/       │     │
│  │  · metrics    │    │ · wecom      │    │ · legal_monitor  │     │
│  └──────⏸️───────┘   │ · logger     │    │ · price_monitor  │     │
│                        │ · helpers    │    └──────────────────┘     │
│                        └──────────────┘                            │
└──────────────────────────────────────────────────────────────────┘
                             ⏸️ = 暂停开发
```

### 数据流

```
股票列表 (新浪) ──→ 股票池 (ST/北交所过滤) ──→ 批量扫描
                                                        │
                              ┌──────────────────────────┤
                              ▼                          ▼
                     K线获取 (腾讯)                预过滤 (MA200/涨幅)
                              │                          │
                              ▼                          │
                     Screener 评估                       │
                    ┌─────────┼─────────┐                │
                    ▼         ▼         ▼                │
              趋势过滤  突破结构  成交量确认              │
              换手率评估  风险标记  市场环境              │
              板块强度  基本面评分  突破阶段              │
                    │                                   │
                    └──────────┬───────────────────────┘
                               ▼
                         130 分综合评分
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                 Buy Stop  谨慎参与  不推荐
                    │
                    ▼
              报告 (JSON + Markdown + CSV + 企业微信)
```

---

## 评分体系

### 130 分制五维评分

| 维度 | 满分 | 权重 | 说明 |
|------|:----:|:----:|------|
| **Technical** | **100** | 76.9% | 趋势 20 + 结构 25 + 量能 20 + 换手 15 + 风险 10 + 板块 10 |
| **Fundamental** | **15** | 11.5% | 业绩预增 / 快报 / 重大合同 / 回购增持（含时间衰减） |
| **Market** | **5** | 3.8% | 沪深300 / 上证 / 创业板三大指数趋势加权 |
| **Sector** | **10** | 7.7% | 个股 vs 板块 5 日超额收益 |
| **Combined** | **130** | 100% | |

### 评级标准

| 评分范围 | 评级 | 说明 |
|:--------:|:----:|------|
| ≥ 105 | **A+** | ⭐ 最佳 Buy Stop 候选 |
| ≥ 95 | **A** | ✅ Buy Stop 候选 |
| ≥ 85 | **B+** | ⚠️ 谨慎参与 |
| ≥ 75 | **B** | 🔍 仅观察 |
| < 75 | **C / NO** | ❌ 不参与 |

### 评分细则

**Technical (100分):**

| 子项 | 满分 | 评分规则 |
|------|:----:|----------|
| 趋势 | 20 | 接近20日高 = 20分；距离20日高 < -3% = 15分 |
| 结构 | 25 | 突破0-1天 = 25分；>5天 = 10分；5日涨幅过大扣分 |
| 量能 | 20 | 量比 ≥ 1.5 = 20分；≥ 1.2 = 12分；×10 保底 |
| 换手 | 15 | 正常区间 = 15分；过高 = 3分；过低或未知 = 7-8分 |
| 风险 | 10 | 每 flag -3分，致命风险 = 0分 |
| 板块 | 10 | 通过板块评分模块计算（与Sector维度独立） |

---

## 突破生命周期

```
时间线 →
                 ═══════════════════════════════════
                 👶               🏃         🚫         🚫
           EARLY_BREAKOUT    TRENDING   EXTENDED    CLIMAX
                 │               │          │          │
                 │ ✅ Buy Stop    │ ✅ 谨慎  │ ⚠️ 降级  │ 🚫 禁止
                 │               │          │          │
                 ▼               ▼          ▼          ▼
            ≤5天,涨幅<20%   5-15天,     >10天或    连板≥3
                           涨幅20-50%   涨幅>30%  或翻倍/50%
```

### 阶段决策逻辑

| 阶段 | Buy Stop | 条件 |
|:----:|:--------:|------|
| **EARLY_BREAKOUT** | ✅ 最佳窗口 | 刚突破 ≤5 天，涨幅 < 20% |
| **TRENDING** | ✅ 谨慎参与 | 趋势运行中，5-15 天 |
| **EXTENDED** | 🚫 降低评级 | 距突破 > 10 天或涨幅 > 30%，仅高分可参与 |
| **CLIMAX** | 🚫 禁止交易 | 连续涨停 ≥ 3 天或 5 日涨幅 > 50% |

---

## 快速开始

### 环境要求

- **Python 3.10+**（推荐 3.11）
- **curl**（macOS / Linux 自带）
- 操作系统：macOS / Linux

> 💡 **本项目核心代码完全使用 Python 标准库，无需安装任何第三方包即可运行。**  
> `feedparser` 为可选依赖，仅 Alibaba Risk Monitor 的 RSS 新闻聚合功能需要。

### 安装

```bash
# 克隆仓库（Private Repo 需先配置 SSH Key）
git clone git@github.com:<你的用户名>/Atlas-Trading-Agent.git
cd Atlas-Trading-Agent

# （推荐）创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装可选依赖（仅 Alibaba Risk Monitor 需要）
pip install -r requirements.txt
```

### 快速验证

```bash
# 确保在项目根目录（Atlas-Trading-Agent/）
pwd
# → /path/to/Atlas-Trading-Agent

# 设置 PYTHONPATH
export PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH"

# 运行扫描测试（扫描前 50 只）
python3 buy_stop_v3/run_scan.py --stocks 50
```

---

## 用法指南

### 扫描

```bash
# 扫描前 100 只股票（快速测试）
python3 buy_stop_v3/run_scan.py

# 全市场扫描（~5000 只，约 15-20 分钟）
python3 buy_stop_v3/run_scan.py --stocks 0

# 沪深300 成分股
python3 buy_stop_v3/run_scan.py --market HS300

# 全市场 + 基本面评分（更慢，约 30 分钟）
python3 buy_stop_v3/run_scan.py --stocks 0 --fundamental

# 关闭基本面评分
python3 buy_stop_v3/run_scan.py --stocks 0 --no-fundamental
```

**退出码含义：**

| 退出码 | 含义 |
|:------:|------|
| 0 | 扫描完成，无候选 |
| 1 | 扫描完成，有候选（通过 `exit_code` 可判断推送策略） |
| 2 | 扫描异常（部分股票出错） |

### 扫描结果

扫描完成后，结果输出到 `buy_stop_v3/output/` 目录：

| 文件 | 格式 | 说明 |
|------|:----:|------|
| `output/json/YYYYMMDD.json` | JSON | 结构化扫描数据（便于程序处理） |
| `output/reports/YYYYMMDD.md` | Markdown | 可读扫描报告（便于人工阅读） |
| `output/signal_history.csv` | CSV | 每日候选历史，每日追加（便于复盘） |
| `logs/` | 文本 | 运行日志（按日轮换，保留 30 天） |

### 回测

> ⚠️ 回测仅用于策略验证，结果仅供参考，不能预测未来。

```bash
# ABCD 单只股票对比回测
python3 -c "
from backtest.engine import BacktestEngineV35, compare_abcd
results = compare_abcd(
    [('000977','浪潮信息'),('600519','贵州茅台')],
    '2023-01-01', '2026-07-24'
)
for cfg, m in results.items():
    print(f'{cfg}: {m.total_trades}笔 胜率{m.win_rate}%')
"
```

**ABCD 模型对比：**

| 配置 | Technical | Fundamental | Market | Sector |
|:----:|:---------:|:-----------:|:------:|:------:|
| **A** | ✅ | ❌ | ❌ | ❌ |
| **B** | ✅ | ✅ | ❌ | ❌ |
| **C** | ✅ | ✅ | ✅ | ❌ |
| **D** | ✅ | ✅ | ✅ | ✅ |

### Alibaba Risk Monitor

独立的风险监控系统，位于 `alibaba_risk_monitor/` 目录：

```bash
cd alibaba_risk_monitor

# 综合扫描（法律 + 新闻 + 价格）
python3 alibaba_risk_monitor.py --all

# 仅法律案件监控
python3 alibaba_risk_monitor.py --legal

# 仅新闻监控
python3 alibaba_risk_monitor.py --news
```

详见其内部注释和 cron 配置。

---

## 配置企业微信

企业微信机器人 Webhook 是 Atlas 唯一的推送方式。

### 1. 创建 Webhook

1. 打开企业微信 → 群聊 → 群设置 → 群机器人
2. 添加机器人 → 复制 Webhook URL

### 2. 设置环境变量

```bash
# 临时设置（当前终端会话）
export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key"

# 永久设置（写入 shell 配置）
echo 'export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key"' >> ~/.zshrc
source ~/.zshrc
```

### 3. 推送规则

| 评级 | 推送策略 |
|:----:|----------|
| A+ (≥105) | ✅ 推送详情（价格、止损、目标、入选原因） |
| A (≥95) | ✅ 推送详情 |
| B+ 及以下 | ❌ 不推送 |
| 无候选 | ✅ 推送"今日无符合条件"通知 |

> 未配置 Webhook 时，扫描正常进行但静默跳过推送。

---

## 配置 Cron

### Buy Stop 扫描（每日收盘后）

```bash
# 编辑 crontab
crontab -e

# 每周一至周五 15:30 运行全市场扫描
30 15 * * 1-5 cd /path/to/Atlas-Trading-Agent && \
  bash buy_stop_v3/run_daily.sh --stocks 0 >> \
  buy_stop_v3/logs/cron.log 2>&1
```

### 使用 run_daily.sh

`run_daily.sh` 是 cron 的包装脚本，自动处理环境激活、日志记录：

```bash
# 手动运行（扫描前 100 只）
bash buy_stop_v3/run_daily.sh

# 全市场
bash buy_stop_v3/run_daily.sh --stocks 0

# 沪深300
bash buy_stop_v3/run_daily.sh --market HS300
```

---

## 项目目录说明

```
Atlas-Trading-Agent/
├── buy_stop_v3/                   # Buy Stop 扫描系统（主项目）
│   ├── config/
│   │   └── settings.py            # 策略参数 + API 配置
│   ├── core/
│   │   ├── screener.py            # 核心筛选引擎（130分制）
│   │   ├── scorer.py              # 评分逻辑（占位文件）
│   │   ├── fundamental_scorer.py  # 基本面评分
│   │   ├── market_regime.py       # 市场环境评分
│   │   ├── sector_scorer.py       # 板块强度评分
│   │   └── breakout_stage.py      # 突破生命周期识别
│   ├── data/
│   │   ├── http_client.py         # curl 子进程 HTTP 客户端
│   │   ├── market_fetcher.py      # K线 + 股票列表获取
│   │   ├── cninfo_fetcher.py      # 巨潮资讯公告抓取
│   │   └── types.py               # 统一数据类型
│   ├── scanner/
│   │   ├── universe.py            # 股票池生成（ST/北交所过滤）
│   │   ├── batch_runner.py        # 批量扫描引擎
│   │   └── report.py              # 报告生成（JSON/Markdown/CSV）
│   ├── backtest/                  # 回测引擎（暂停开发）
│   │   ├── engine.py              # 回测引擎 V3.5（ABCD 对比）
│   │   └── metrics.py             # 回测指标计算
│   ├── utils/
│   │   ├── logger.py              # 日志（按日轮换）
│   │   ├── notifier.py            # 企业微信通知
│   │   ├── wecom.py               # 推送预留（已弃用）
│   │   └── helpers.py             # 工具函数 / 文件缓存
│   ├── run_scan.py                # 全市场扫描入口
│   ├── run_daily.sh               # cron 启动脚本
│   ├── main.py                    # 占位入口（未启用）
│   └── .gitignore                 # buy_stop_v3 级别 gitignore
├── alibaba_risk_monitor/          # 阿里巴巴风险监控（独立项目）
│   ├── alibaba_risk_monitor.py    # 主监控脚本
│   ├── legal_monitor.py           # 法律案件监控
│   └── config.py                  # 配置
├── tests/                         # 测试套件（53 项）
│   ├── test_screener.py
│   ├── test_scanner.py
│   ├── test_backtest.py
│   ├── test_notifier.py
│   ├── test_market_fetcher.py
│   ├── test_market_regime.py
│   ├── test_sector_scorer.py
│   ├── test_fundamental_scorer.py
│   ├── test_breakout_stage.py
│   ├── test_cninfo.py
│   ├── test_screener_fundamental.py
│   └── test_screener_v32_integration.py
├── docs/                          # 文档
├── scripts/                       # 辅助脚本
├── AGENT.md                       # AI Agent 人格文件
├── MEMORY.md                      # 项目状态记录
├── TASKS.md                       # 任务列表
├── CHANGELOG.md                   # 版本历史
├── README.md                      # 本文件
├── requirements.txt               # 依赖（仅 feedparser）
├── LICENSE                        # MIT License
└── .gitignore                     # 全局 gitignore
```

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| **运行时** | Python 3.11+ | 标准库为主，零硬性第三方依赖 |
| **HTTP 客户端** | curl 子进程 | 绕过 Python SSL 栈兼容性问题 |
| **K线数据源** | 腾讯财经 API | `web.ifzq.gtimg.cn` |
| **股票列表** | 新浪财经 API | `vip.stock.finance.sina.com.cn` |
| **基本面数据** | 巨潮资讯网 | `www.cninfo.com.cn` |
| **备用数据源** | 东方财富 API | `push2his.eastmoney.com`（限速 5-10次/分钟） |
| **通知** | 企业微信机器人 | Webhook POST |
| **部署** | macOS / Linux | crontab 无人值守 |
| **版本控制** | Git | GitHub Private Repo |

---

## 开发指南

### 开发环境

```bash
# 使用 Hermes venv 或新建 venv
python3 -m venv venv
source venv/bin/activate

# 安装开发工具
pip install ruff pytest

# 运行 lint 检查
ruff check buy_stop_v3/
ruff check tests/
```

### 代码规范

- **PEP 8** 编码风格
- 所有公共函数必须有 **docstring**
- 使用结构化 `logging`（不用 `print`）
- 类型注解优先使用 `typing` 模块
- 异常必须被显式捕获，不使用裸 `except:`

### 禁止事项

参见 `AGENT.md` 完整说明。核心要点：

1. ❌ **不要修改交易策略参数**
2. ❌ **不要修改评分逻辑**
3. ❌ **不要修改 Buy Stop 规则**
4. ❌ **不要新增交易策略**
5. ❌ **不要修改风控规则**
6. ❌ **不要硬编码密钥**

---

## 测试

测试套件位于 `tests/` 目录，共 53 项测试，覆盖全部核心模块。

```bash
# 方法一：pytest
cd Atlas-Trading-Agent
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 -m pytest tests/ -v

# 方法二：直接运行单个测试
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 tests/test_screener.py

# 方法三：运行所有测试
for t in tests/test_*.py; do
  PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 "$t"
done
```

### 测试覆盖

| 模块 | 测试文件 | 数量 |
|------|----------|:----:|
| 筛选引擎 | `test_screener.py` | 12+ |
| 筛选集成 | `test_screener_fundamental.py` | 8+ |
| V3.2 集成 | `test_screener_v32_integration.py` | 6+ |
| 全市场扫描 | `test_scanner.py` | 6+ |
| 回测引擎 | `test_backtest.py` | 4+ |
| 行情获取 | `test_market_fetcher.py` | 6+ |
| 企业微信 | `test_notifier.py` | 5+ |
| 市场环境 | `test_market_regime.py` | 2+ |
| 板块强度 | `test_sector_scorer.py` | 2+ |
| 基本面评分 | `test_fundamental_scorer.py` | 2+ |
| 突破生命周期 | `test_breakout_stage.py` | 2+ |
| 巨潮资讯 | `test_cninfo.py` | 2+ |

---

## Roadmap

### 🟢 已完成（V3.4）
- [x] Buy Stop 130 分五维评分体系
- [x] 全市场批量扫描引擎
- [x] 突破生命周期识别
- [x] 市场环境 / 板块强度 / 基本面评分
- [x] 企业微信推送
- [x] 回测引擎（暂停）
- [x] Alibaba Risk Monitor（独立）
- [x] 工程标准化（README/AGENT/MEMORY/TASKS/CHANGELOG）

### 🟡 进行中
- [ ] GitHub Remote 配置 + Push
- [ ] 云服务器部署
- [ ] PostgreSQL 存储

### 🔵 计划中
- [ ] 历史信号分析仪表盘
- [ ] 更多基本面数据（财报/龙虎榜/北向资金）
- [ ] Web 管理面板（简单）

### ⚪ 远期
- [ ] 多时间框架分析
- [ ] LLM 新闻情绪分析
- [ ] QMT 自动交易对接

---

## 注意事项

### ⚠️ 策略风险

1. **A 股 T+1 交易制度** — 当日买入不可卖出，存在隔夜风险
2. **本系统仅提供技术分析信号** — 不构成投资建议
3. **回测结果不代表未来收益** — 历史表现不能预测未来
4. **实盘交易需自行评估风险** — 请根据自身风险承受能力决策
5. **数据源可能变更** — 腾讯/新浪/巨潮 API 随时可能调整，需关注更新
6. **市场环境变化** — 策略在牛市中表现更优，熊市信号减少属于正常

### 🔒 安全

1. **不要提交 API Key / Webhook URL 到 Git** — `.gitignore` 已配置
2. **使用环境变量存储敏感信息** — 见 [配置企业微信](#配置企业微信)
3. **Private Repository** — 建议使用 GitHub 私有仓库
4. **定期轮换 Webhook Key** — 避免泄露

### 💡 最佳实践

1. **每日收盘后运行** — A 股交易时间 9:30-15:00，建议 15:30 后运行
2. **结合盘面分析** — 信号需要人工确认，不要盲目买入
3. **分散持股** — 不要全仓单只股票
4. **回测验证后再实盘** — 任何参数调整先回测再实盘
5. **持续监控数据源** — 定期确认数据获取正常

---

## License

[MIT](LICENSE) © 2026 Atlas Trading Agent

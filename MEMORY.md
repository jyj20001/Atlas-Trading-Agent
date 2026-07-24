# MEMORY.md — Atlas Trading Agent 项目状态记录

> 本文件用于在 AI Agent 新 Session 启动时快速恢复上下文。  
> 新的 Agent 请先读取本文件，再读取 AGENT.md 获取工作原则。

---

## 当前项目状态

**版本:** v3.4-production  
**状态:** 生产运行中  
**最后更新:** 2026-07-24  
**运行频率:** 每日收盘后（15:00 后）通过 cron 自动扫描  
**推送方式:** 企业微信机器人 Webhook

---

## 已完成的模块

### ✅ Buy Stop V3.4 — 生产版
- **入口:** `run_scan.py`（全市场扫描）/ `run_daily.sh`（cron 包装）
- **核心:** `core/screener.py` — StockScreener 筛选引擎（130分制）
- **数据层:** `data/market_fetcher.py`（腾讯K线 + 新浪列表）/ `data/cninfo_fetcher.py`（巨潮资讯）
- **HTTP:** `data/http_client.py` — curl 子进程，完全绕过 Python SSL 栈
- **扫描引擎:** `scanner/batch_runner.py` — 异常隔离、重试、进度输出
- **股票池:** `scanner/universe.py` — ST/北交所过滤、上市天数判断
- **报告:** `scanner/report.py` — JSON + Markdown + CSV
- **通知:** `utils/notifier.py` — 企业微信（A+ 级推送详情）
- **评分:** 五维评分（技术100 + 基本面15 + 市场5 + 板块10 = 130分）
- **日志:** `utils/logger.py` — 按日轮换，保留30天

### ✅ Breakout Stage 生命周期识别
- BreakoutStageIdentifier（core/breakout_stage.py）
- 四阶段: EARLY_BREAKOUT (✅) → TRENDING (⚠️) → EXTENDED (🚫) → CLIMAX (🚫)

### ✅ 市场环境评分
- MarketRegimeScorer（core/market_regime.py）
- 沪深300 / 上证 / 创业板三大指数综合评估

### ✅ 板块强度评分
- SectorScorer（core/sector_scorer.py）
- 覆盖 30+ A股行业板块

### ✅ 基本面评分
- FundamentalScorer（core/fundamental_scorer.py）
- 业绩预增 / 快报 / 重大合同 / 回购增持

### ✅ 企业微信推送
- A+ (>=105) 和 A (>=95) 级推送详情
- 无候选时推送通知
- 未配置 Webhook 时静默跳过

### ✅ Alibaba Risk Monitor（独立项目）
- 路径: `alibaba_risk_monitor/`
- 功能: 法律案件 + 政策新闻 + 价格成交量异常
- 推送: 企业微信
- 运行: cron 定时（每 15 分钟价格监控 + 每 30 分钟综合扫描）

---

## 暂停开发的模块

### ⏸️ 回测引擎
- **路径:** `backtest/engine.py` + `backtest/metrics.py`
- **状态:** 已稳定，不再继续开发
- **原因:** 回测结果仅供参考，不能预测未来。当前 A/B/C/D 对比功能已满足需求。
- **保留:** 保留在仓库中但不再主动迭代。如需修复 bug 可改，但不新增特性。

---

## 未来计划

### 🔄 工程层面（短期）
1. **GitHub 公开（Private Repo）** — 完成工程标准化后上传
2. **云服务器部署** — 迁移到国内云服务器（阿里云/腾讯云）
3. **PostgreSQL 存储** — 替代 CSV/JSON 文件存储
4. **历史信号数据库** — 建立信号数据库以便复盘分析
5. **Web 面板（可选）** — 简单的扫描结果看板

### 🔭 数据层面（中期）
1. **更多基本面数据** — 财报数据 RPA 抓取
2. **龙虎榜数据** — 游资/机构动向监控
3. **北向资金数据** — 外资持股变动
4. **融券余额数据** — 做空压力监控

### 🌟 策略层面（长期 — 新项目）
1. **多时间框架分析** — 日线 + 周线 + 60分钟联合判断
2. **AI 辅助评分** — 用 LLM 分析新闻情绪
3. **自动化交易** — QMT 对接

---

## 关键设计理念

### 为什么采用 Buy Stop 策略？

| 原因 | 说明 |
|------|------|
| **趋势跟踪** | Buy Stop 是经典的趋势跟踪策略，在 A 股牛市中表现优异 |
| **机械化** | 规则明确、可编程、无主观判断 |
| **风险可控** | 严格的突破确认 + 止损，避免抄底摸顶 |
| **适合自动扫描** | 可以完全自动化，每日收盘后跑一遍即可 |

### 为什么采用 130 分体系？

1. **多维度评估** — 单纯的技术面评分容易受波动影响，加入基本面/市场/板块后更稳定
2. **可解释性** — 每个维度的分数都有明确含义，知道为什么评分高/低
3. **可调整性** — 每类因子独立计算，后续可以分别验证各因子的预测能力
4. **风控融合** — 风险标记直接融入评分，高风险项自动降分或排除

### 为什么严格风控？

A 股的特殊性决定了严格风控的必要性：

- **连续涨停** → 高位接盘风险极高，必须排除
- **5日涨幅过大** → 短期获利盘巨大，追涨风险极大
- **CLIMAX 阶段** → 行情末端，随时可能崩盘
- **T+1 限制** → 当日买入不可卖出，没有容错空间
- **基本面差** → 可能面临黑天鹅事件（ST、退市、炸雷）

**宁可错过，不可做错** — 这是 Atlas Trading Agent 的风控底线。

### 为什么使用 curl 子进程？

Python 的 urllib / requests 在特定网络环境下会出现 SSL 兼容性问题（证书验证失败、TLS 握手失败等），而 curl 是最稳定的 HTTP 客户端之一。使用 subprocess 调用 curl 可以：

- 利用系统自带的 curl（macOS/Linux 预装）
- 完全绕过 Python SSL 栈的兼容性问题
- 支持 --noproxy 避免代理干扰
- 无需安装任何第三方 HTTP 库

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 运行时 | Python 3.11+（标准库为主） |
| HTTP | curl 子进程 |
| K线数据 | 腾讯财经 API（web.ifzq.gtimg.cn） |
| 股票列表 | 新浪财经 API |
| 基本面数据 | 巨潮资讯网（www.cninfo.com.cn） |
| 通知 | 企业微信机器人 Webhook |
| 部署 | macOS / Linux + crontab |
| 版本控制 | Git (GitHub Private Repo) |

---

## 已知的局限性

1. **数据源依赖** — 腾讯/新浪/巨潮 API 可能随时变更，需监控
2. **回测模拟性** — 回测采用收盘价模拟，无法完全模拟真实成交情况
3. **A 股 T+1** — 当日买入不可卖出，突破买入可能存在次日低开风险
4. **无盘中和分时数据** — 仅使用日K线，无法分析分时走势
5. **北交所不支持** — 故意排除，因流动性不足
6. **仅做扫描** — 不自动下单，需要人工确认
7. **无多时间框架** — 仅使用日线，没有周线/60分钟线联合判断

---

## 项目文件结构

```
Atlas-Trading-Agent/
├── buy_stop_v3/
│   ├── config/          # 配置管理
│   ├── core/            # 筛选引擎 + 五维评分 + 突破生命周期 + 板块/市场/基本面评分
│   ├── data/            # 行情获取 + 基本面数据 + HTTP客户端 + 数据类型
│   ├── scanner/         # 股票池 + 批量扫描 + 报告生成
│   ├── backtest/        # 回测引擎（暂停开发）
│   ├── utils/           # 日志 + 通知 + 工具
│   ├── run_scan.py      # 扫描入口
│   ├── run_daily.sh     # cron 启动脚本
│   └── main.py          # 占位（未启用）
├── alibaba_risk_monitor/
│   ├── alibaba_risk_monitor.py
│   ├── legal_monitor.py
│   └── config.py
├── tests/               # 测试套件（53 项测试）
├── docs/                # 文档
├── scripts/             # 辅助脚本
├── AGENT.md             # AI Agent 人格文件
├── MEMORY.md            # 项目状态记录
├── TASKS.md             # 任务列表
├── CHANGELOG.md         # 版本历史
├── README.md            # 项目说明
├── requirements.txt     # 依赖
├── LICENSE              # MIT License
└── .gitignore
```

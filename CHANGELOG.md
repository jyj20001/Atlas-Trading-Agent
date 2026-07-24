# Atlas Trading Agent 变更日志

## [v3.4-production] — 2026-07-24
### 新增
- 全市场高频扫描引擎（BatchRunner），支持异常隔离和进度输出
- 上市天数过滤（universe.py 中按代码前缀近似判断）
- 预过滤模块（_prefilter），减少无效K线请求
- 企业微信推送优化：TOPN按分数排序、排除低分候选
- 多市场支持（HS300 成分股）

### 修复
- 日志文件无限增长 → 改为按日轮换 TimedRotatingFileHandler
- HTTP 客户端使用 curl 子进程替代 Python SSL 栈以减少 SSLError
- 实盘中 5 日涨幅和距离 20 日高计算修复（使用不含今天的数据）
- 板块评分指数代码修复（腾讯API key 动态检测）
- 回测中基本面评分去除未来函数

### 优化
- 全市场扫描速度优化至 ~0.2 秒/只（预过滤+缓存）
- 市场环境评分缓存避免重复请求
- 53 项测试覆盖全部核心模块

---

## [v3.3] — 2026-07
### 新增
- 市场环境评分模块（MarketRegimeScorer）
  - 沪深300 / 上证 / 创业板三大指数趋势评估
  - 输出 0~5 分 + bull/neutral/bear 状态
- 板块强度评分模块（SectorScorer）
  - 个股 vs 板块指数 5 日超额收益
  - 覆盖 30+ A股行业板块
- 评分体系升级：技术 100 + 基本面 15 + 市场 5 + 板块 10 = 130 分
- 全市场扫描入口 run_scan.py（支持 --stocks / --market / --fundamental）

### 修复
- 行业板块指数代码动态匹配而非硬编码
- 基本面评分在无数据时返回默认值而非抛出异常

### 优化
- 板块代码模糊匹配（关键词包含关系）
- BatchRunner 进度输出 + ETA 估算

---

## [v3.2] — 2026-06
### 新增
- 突破生命周期识别模块（BreakoutStageIdentifier）
  - EARLY_BREAKOUT / TRENDING / EXTENDED / CLIMAX 四阶段
  - CLIMAX 阶段自动禁止交易
- 风控模块增强：高位放量长上影线检测
- 连续涨停阈值从 3 天改为可配置

### 修复
- NO_BREAKOUT 阶段误判为候选的 bug
- EXTENDED 阶段评分不足时不正确降级

### 优化
- 评分逻辑重构为独立 _scorer 方法
- 风险标记合并到评分中

---

## [v3.1] — 2026-06
### 新增
- 基本面评分模块（FundamentalScorer）
  - 业绩预增 / 快报 / 重大合同 / 回购增持
  - 时间衰减机制
  - 与 Screener 合并的 merge_fundamental_score 工具函数
- 企业微信推送（notifier.py）
  - Markdown 格式，A+ 级推送详情
  - 静默跳过未配置
- 独立回测引擎（BacktestEngineV3）
  - A/B/C/D 四种配置对比
  - 交易成本模拟（佣金+印花税+滑点）
  - 止损/止盈/超时三种退出逻辑

### 修复
- K线不足 200 天时 prefilter 正确处理
- 单只异常不中断全流程

### 优化
- K线获取增加重试机制
- 测试套件覆盖率提升

---

## [v3.0] — 2026-05
### 新增
- 核心筛选引擎（StockScreener）
- 130 分制五维评分体系
- A 股 Buy Stop 趋势突破策略
- 数据层重构：
  - market_fetcher.py（腾讯K线 + 新浪列表）
  - cninfo_fetcher.py（巨潮资讯公告）
  - http_client.py（curl 子进程 HTTP）
  - types.py（统一数据类型）
- 日志系统（按日轮换，保留 30 天）
- 项目配置化（config/settings.py）

### 结构
- 初始代码目录结构建立
- MIT License

---

## [v2.0] — 2026-04
### 新增
- Buy Stop 策略原型
- 单股票手动回测工具
- 基础评分指标（趋势+结构+量能）

*注：V2 为独立开发阶段，未保留独立版本记录。*

---

## [v1.0] — 2026-03
### 新增
- Buy Stop 策略概念验证
- A 股行情数据获取原型
- 简单的 Buy Stop 价格计算

*注：V1 为最初的概念验证阶段。*

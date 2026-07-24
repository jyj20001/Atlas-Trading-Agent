# Atlas Trading Agent Development Workflow

> 本文件定义 Atlas Trading Agent 项目的长期开发规范、AI Agent 工作流程和 Git 操作标准。
> 所有参与本项目开发的 AI Agent 和人类开发者均应遵守。

---

## 1. 项目定位

Atlas Trading Agent 是长期维护的 A 股趋势突破交易系统，目标是每天稳定运行、持续输出高质量信号，而非快速迭代功能。

### 核心原则

| 原则 | 说明 |
|------|------|
| **稳定优先** | 生产系统的稳定性高于任何新功能 |
| **可回滚** | 每次变更必须可回退，通过 Git 版本控制保证 |
| **可验证** | 任何代码修改必须有对应的测试验证 |
| **不破坏已有策略** | 核心评分、过滤、风控规则受保护，不经确认不得修改 |

---

## 2. AI Agent 工作流程

任何代码修改必须遵守以下流水线：

```
需求确认
    ↓
读取 AGENT.md / MEMORY.md / TASKS.md
    ↓
检查 git status（确认当前工作树状态）
    ↓
修改代码
    ↓
运行相关测试
    ↓
更新文档（README / CHANGELOG / MEMORY / TASKS）
    ↓
git commit（规范格式）
    ↓
重大版本创建 tag
```

### 禁止行为

- ❌ 未测试直接提交
- ❌ 直接修改 main 分支关键逻辑（评分、风控、参数）
- ❌ 删除已有功能
- ❌ 修改交易参数但未经过确认
- ❌ 提交数据库、日志、输出文件到 Git

### 新 Session 启动流程

新的 AI Agent Session 启动时，应首先读取以下文件以恢复上下文：

1. `AGENT.md` — AI Agent 人格、核心原则、禁止事项
2. `MEMORY.md` — 项目状态、模块清单、已知局限性
3. `TASKS.md` — 已完成/进行中/计划中的任务
4. `docs/development_workflow.md` — 本文件

然后输出：
- 当前版本
- 最近完成的工作
- 正在进行的工作
- 下一步建议

---

## 3. Git 规范

### Commit 格式

```
<type>: <简短描述>
```

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新增功能 | `feat: add sqlite market database layer` |
| `fix` | 修复问题 | `fix: repair market data fallback` |
| `refactor` | 代码重构 | `refactor: extract http client module` |
| `docs` | 文档修改 | `docs: add long term development workflow` |
| `test` | 测试相关 | `test: add signal database tests` |
| `perf` | 性能优化 | `perf: batch kline fetch with cache` |

**规范：**
- 第一行不超过 72 字符
- 使用英文（项目统一语言）
- 动词用原形（add, fix, refactor 而非 added, fixed）
- 描述要清晰说明"做了什么"，而非"为什么做"

### 分支策略

| 分支 | 用途 | 合并来源 |
|------|------|----------|
| `main` | 生产分支，始终保持可运行 | 仅从 `develop` 合并 |
| `develop` | 开发分支，日常开发 | 功能分支合并 |
| `feature/*` | 功能分支 | 从 `develop` 切出 |

### 版本 Tag 规则

小修改（文档、测试、bug fix）：commit 即可，无需 tag。

重大功能或架构变更：必须创建 tag。

格式：`v<主版本>.<次版本>-<功能名称>`

示例：
- `v3.5-data-layer` — 新增 SQLite 数据库层
- `v3.6-parallel-scanner` — 并行扫描优化
- `v4.0-cloud-agent` — 云部署架构升级

---

## 4. 测试要求

任何代码修改必须运行相关测试。

### 测试分类

| 类型 | 位置 | 运行命令 |
|------|------|----------|
| 数据层测试 | `tests/test_market_fetcher.py` | `python tests/test_market_fetcher.py` |
| 筛选引擎测试 | `tests/test_screener.py` | `python tests/test_screener.py` |
| 基本面评分测试 | `tests/test_fundamental_scorer.py` | `python tests/test_fundamental_scorer.py` |
| 信号数据库测试 | `tests/test_signal_database.py` | `python tests/test_signal_database.py` |
| 通知模块测试 | `tests/test_notifier.py` | `python tests/test_notifier.py` |
| Scanner 测试 | `tests/test_scanner.py` | `python tests/test_scanner.py` |

### 测试报告格式

修改完成后，报告应包含：

```
修改文件：
测试命令：
测试结果：
风险说明：
```

---

## 5. 数据安全规则

以下内容**禁止**提交到 Git 仓库：

| 类别 | 规则 | 说明 |
|------|------|------|
| 数据库 | `*.db`, `*.sqlite`, `*.sqlite3` | SQLite 运行时数据 |
| 日志 | `logs/` | 运行日志和 cron 输出 |
| 运行输出 | `output/` | 扫描结果 JSON/Markdown/CSV |
| 缓存 | `data/.cache/` | API 响应缓存 |
| 密钥 | `.env`, `*.key`, `*.pem` | 环境变量和证书 |

GitHub 只保存：

- 代码文件（`.py`）
- 配置模板（`config/settings.py`）
- 文档（`docs/*.md`, `README.md`, `AGENT.md`, `MEMORY.md`, `TASKS.md`, `CHANGELOG.md`）
- 测试文件（`tests/*.py`）
- 启动脚本（`run_scan.py`, `run_daily.sh`）

---

## 6. 交易策略保护规则

以下文件属于**核心资产**，受特殊保护：

```
core/screener.py              — 筛选引擎
core/fundamental_scorer.py    — 基本面评分
core/market_regime.py         — 市场环境评分
core/sector_scorer.py         — 板块强度评分
core/breakout_stage.py        — 突破生命周期
config/settings.py            — 策略参数
```

**AI Agent 不得：**

- 自行降低过滤条件（评分阈值、量比要求等）
- 修改评分权重（技术100 / 基本面15 / 市场5 / 板块10）
- 修改 Buy Stop 规则（触发价计算、止损计算、突破识别）
- 修改风控参数（连续涨停过滤、涨幅限制等）

如需修改上述内容，必须：
1. 先提交 Issue 说明理由
2. 经过回测验证
3. 用户明确确认后实施

---

## 7. 文档维护规则

每个重大版本更新必须同步更新以下文件：

| 文件 | 必须更新内容 |
|------|-------------|
| `README.md` | 功能清单、使用方法、项目结构 |
| `MEMORY.md` | 已完成的模块、暂停的模块、当前状态 |
| `TASKS.md` | 已完成 ✅ → 进行中 🔄 → 已完成 |
| `CHANGELOG.md` | 新增内容、修复内容、优化内容 |
| `docs/development_workflow.md` | 本文件（如有流程变更） |

---

## 8. 代码风格

- 严格遵守 PEP 8
- 所有公共函数必须有 docstring
- 日志使用结构化 logging（不用 print）
- 类型注解优先使用 typing 模块
- 异常必须被显式捕获，不使用裸 `except:`

---

## 9. 发布流程

```
1. develop 分支完成功能和测试
2. 合并到 main 分支（git merge --no-ff）
3. 更新 CHANGELOG.md
4. 打 tag（git tag -a vX.Y-<name> -m "<描述>"）
5. 推送（git push origin main && git push origin --tags）
```

# Release Checklist — Atlas Trading Agent v3.4-production

> 发布前按顺序逐项检查。所有项完成后方可发布。

---

## 一、发布前检查

### 1.1 代码质量
- [ ] `git status` — 工作区干净，无未提交修改
- [ ] `git log —oneline` — 确认所有变更已记录
- [ ] 无 `# TODO`、`# FIXME`、`print()` 调试输出残留
- [ ] 无空 `except:` 或 `except Exception: pass`
- [ ] 所有函数有 docstring（至少核心模块）
- [ ] 无硬编码密钥或 Webhook URL

### 1.2 导入检查
- [ ] 所有 `from x import y` 正确且无循环引用
- [ ] `__init__.py` 导出的函数实际可用
- [ ] `requirements.txt` 与实际代码匹配

### 1.3 文件完整性
- [ ] `README.md` 存在且内容完整
- [ ] `AGENT.md` 存在且内容完整
- [ ] `MEMORY.md` 存在且内容完整
- [ ] `TASKS.md` 存在且内容完整
- [ ] `CHANGELOG.md` 更新至当前版本
- [ ] `LICENSE` 存在
- [ ] `.gitignore` 覆盖所有敏感文件类型
- [ ] `docs/code_audit.md` 存在

### 1.4 环境检查
- [ ] Python 版本 >= 3.10（推荐 3.11）
- [ ] `curl` 命令可用（macOS/Linux 自带）
- [ ] 网络可访问腾讯财经 API (`web.ifzq.gtimg.cn`)
- [ ] 网络可访问新浪财经 API (`vip.stock.finance.sina.com.cn`)
- [ ] 网络可访问巨潮资讯网 (`www.cninfo.com.cn`)

---

## 二、测试验证

### 2.1 模块导入测试
```bash
cd Atlas-Trading-Agent
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 -c "
import config.settings
import data.types
import data.http_client
import utils.logger
import utils.helpers
import utils.notifier
import core.breakout_stage
import core.market_regime
import core.sector_scorer
import core.fundamental_scorer
import core.screener
import scanner.universe
import scanner.batch_runner
import scanner.report
import backtest.metrics
print('✅ 全部模块导入成功')
"
```

- [ ] 无导入错误

### 2.2 测试运行
```bash
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 tests/test_screener.py
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 tests/test_scanner.py
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 tests/test_notifier.py
# ... 逐一运行或使用 pytest
```

- [ ] 所有测试通过
- [ ] 无意外报错

### 2.3 快速扫描测试
```bash
PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH" python3 buy_stop_v3/run_scan.py --stocks 10
```

- [ ] 正常输出 "Buy Stop V3 扫描完成"
- [ ] `output/` 目录生成当日 JSON + Markdown 报告
- [ ] 退出码为 0 或 1（无异常）

---

## 三、Git Commit

### 3.1 提交所有修改
```bash
git status          # 确认变更列表
git add -A          # 暂存全部
git commit -m "feat: v3.4-production 工程标准化

- 项目标准化目录结构
- README/AGENT/MEMORY/TASKS/CHANGELOG 文档全套
- .gitignore 增强
- 删除死代码 (main.py, wecom.py, today_str())
- 修复 run_scan.py 缺失 import os
- 测试文件路径修复
"
```

### 3.2 Git 用户信息（首次需配置）
```bash
git config user.name "Your Name"
git config user.email "your@email.com"
```

- [ ] Commit 完成
- [ ] Commit message 规范

---

## 四、Git Tag

### 4.1 验证 Tag
```bash
git tag -l 'v*'     # 列出已有 tag
```

### 4.2 创建版本 Tag
```bash
# 主版本 tag（生产发布）
git tag -a v3.4-production -m "v3.4-production — Buy Stop 工程标准化生产版本"

# 也可创建语义化 tag
git tag -a v3.4.0 -m "v3.4.0 — 语义化版本（可选）"
```

- [ ] Tag 已创建
- [ ] Tag 名称规范

---

## 五、Git Push

### 5.1 GitHub Private Repository 创建
1. 打开 https://github.com/new
2. 仓库名称: `Atlas-Trading-Agent`
3. 选择 **Private**（不要公开）
4. 不要勾选 "Initialize with README"（已有）
5. 点击 "Create repository"

### 5.2 添加 Remote
```bash
git remote add origin git@github.com:<你的用户名>/Atlas-Trading-Agent.git
```

### 5.3 Push 到 GitHub
```bash
# Push main 分支
git push -u origin main

# Push develop 分支
git push origin develop

# Push tags
git push --tags
```

- [ ] `main` 分支推送成功
- [ ] `develop` 分支推送成功
- [ ] Tag `v3.4-production` 推送成功
- [ ] GitHub 页面可见代码

---

## 六、发布后检查

### 6.1 GitHub 页面检查
- [ ] README.md 渲染正常
- [ ] 无大文件（单文件 < 1MB）
- [ ] 目录结构正确
- [ ] .gitignore 生效（无缓存/日志/venv）

### 6.2 Repository Settings
- [ ] 设置 Private（确认）
- [ ] 禁用 Issues（如果不需要）
- [ ] 禁用 Wiki（如果不需要）
- [ ] 添加 Collaborator（如需多人协作）
- [ ] 添加 Branch Protection（main 和 develop）

### 6.3 Release 创建（GitHub）
```bash
# 可选：在 GitHub 页面创建 Release
# Repo → Releases → Create a new release
# Tag: v3.4-production
# Title: Atlas Trading Agent v3.4-production
# Description: 请参考 CHANGELOG.md
```

- [ ] GitHub Release 已创建（可选）

---

## 七、恢复方法

详见 `docs/restore.md`。

快速恢复命令：
```bash
git clone git@github.com:<用户名>/Atlas-Trading-Agent.git
cd Atlas-Trading-Agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# 设置 WECOM_WEBHOOK_URL
# 设置 COURTLISTENER_API_TOKEN
# 配置 crontab
```

---

## 八、升级方法

### 从本地旧版本升级
```bash
# 备份旧配置
cp -r ~/buy_stop_v3 ~/backup_buy_stop_v3_$(date +%Y%m%d)

# 克隆新仓库
cd ~
git clone git@github.com:<用户名>/Atlas-Trading-Agent.git

# 恢复环境变量
export WECOM_WEBHOOK_URL="你的Key"

# 恢复 cron
crontab -e
# 添加: 30 15 * * 1-5 /path/to/run_daily.sh --stocks 0
```

### 从 GitHub 更新
```bash
cd ~/Atlas-Trading-Agent
git pull origin main
# 检查 CHANGELOG.md 了解变更
```

---

## 九、健康检查清单（Post-Release）

- [ ] 当天手动运行一次扫描
- [ ] 确认企业微信正常推送
- [ ] 确认日志正常输出
- [ ] 确认 output/ 报告正常生成
- [ ] 确认 Alibaba Risk Monitor cron 正常运行
- [ ] 24 小时后检查日志无异常增长

# Atlas Trading Agent — 灾难恢复指南

> 本指南用于电脑损坏、数据丢失等灾难场景下，**从头恢复整个交易系统**。  
> 任何 AI Agent 读取本文件后即可独立完成恢复。

---

## 一、恢复概览

### 恢复流程

```text
1. 安装系统依赖    →  Python, curl, git
2. 克隆仓库        →  git clone
3. 创建虚拟环境    →  python3 -m venv
4. 安装依赖        →  pip install
5. 配置环境变量    →  WECOM_WEBHOOK_URL + COURTLISTENER_API_TOKEN
6. 验证导入        →  测试模块导入
7. 配置 cron       →  crontab 自动扫描
8. 验证运行        →  手动扫描测试
```

### 预期耗时

| 步骤 | 时间 | 说明 |
|------|:----:|------|
| 系统依赖安装 | 5 分钟 | macOS 自带 |
| 仓库克隆 | 1 分钟 | GitHub Private Repo |
| 虚拟环境 | 2 分钟 | python3 -m venv |
| 环境变量配置 | 2 分钟 | 需有 Webhook URL |
| 验证运行 | 5 分钟 | 扫描前 10 只测试 |
| **总计** | **~15 分钟** | |

---

## 二、系统要求

### 硬件
- macOS (推荐) 或 Linux
- 网络连接（用于访问腾讯/新浪/巨潮 API）

### 软件
| 软件 | 版本 | 来源 |
|------|:----:|------|
| Python | >= 3.10 | `python3 --version` 检查 |
| curl | 任意版本 | macOS/Linux 预装 |
| git | 任意版本 | macOS 预装或 `brew install git` |

### 网络要求
- ✅ 可访问 `web.ifzq.gtimg.cn`（腾讯K线）
- ✅ 可访问 `vip.stock.finance.sina.com.cn`（新浪股票列表）
- ✅ 可访问 `www.cninfo.com.cn`（巨潮资讯）
- ❌ 无需科学上网（所有数据源国内可用）

---

## 三、恢复步骤

### 步骤 1：安装 Python（如果没有）

```bash
# macOS (使用 Homebrew)
/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
brew install python@3.11

# 验证
python3 --version
# → Python 3.11.x
```

### 步骤 2：克隆仓库

```bash
# 确保已配置 GitHub SSH Key（如没有）
ssh-keygen -t ed25519 -C "your@email.com"
cat ~/.ssh/id_ed25519.pub
# 将此内容粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key

# 克隆
cd ~
git clone git@github.com:<你的用户名>/Atlas-Trading-Agent.git
cd Atlas-Trading-Agent

# 切换到最新稳定版本
git checkout main

# 查看 tag
git tag -l
# → v3.4-production

# 如需要特定版本
git checkout v3.4-production
```

### 步骤 3：创建虚拟环境

```bash
cd ~/Atlas-Trading-Agent
python3 -m venv venv
source venv/bin/activate

# 验证 Python 版本
python3 --version
# → Python 3.11.x

# 设置 PYTHONPATH（方便模块导入）
export PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH"

# 可选：写入 shell 配置文件
echo 'export PYTHONPATH="$HOME/Atlas-Trading-Agent/buy_stop_v3:$PYTHONPATH"' >> ~/.zshrc
```

### 步骤 4：安装依赖

```bash
cd ~/Atlas-Trading-Agent
source venv/bin/activate

pip install -r requirements.txt

# 验证
pip list | grep feedparser
# → feedparser 6.x.x
```

> 💡 **核心代码无需第三方依赖即可运行。** `feedparser` 仅 Alibaba Risk Monitor 使用。

### 步骤 5：配置环境变量

#### 5a. 企业微信 Webhook

```bash
# 从之前的企业微信群获取 Webhook URL
export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key"

# 写入 shell 配置（持久化）
echo 'export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key"' >> ~/.zshrc
source ~/.zshrc
```

> 如何获取 Webhook URL：打开企业微信 → 群聊 → 群设置 → 群机器人 → 添加机器人 → 复制 Webhook URL

#### 5b. Alibaba Risk Monitor API Token（可选）

```bash
# 如需法律案件监控，需 CourtListener API Token
# 注册：https://www.courtlistener.com/
export COURTLISTENER_API_TOKEN="你的token"

# 写入配置文件
echo 'export COURTLISTENER_API_TOKEN="你的token"' >> ~/.zshrc
```

> 不设置 Token 也可运行（部分法律监控功能降级为 RSS 备选方案）。

### 步骤 6：验证核心模块

```bash
cd ~/Atlas-Trading-Agent
source venv/bin/activate
export PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH"

# 验证所有模块可导入
python3 -c "
import sys; sys.path.insert(0, 'buy_stop_v3')
modules = [
    'config.settings', 'data.types', 'data.http_client', 'data.market_fetcher',
    'utils.logger', 'utils.helpers', 'utils.notifier',
    'core.screener', 'core.fundamental_scorer', 'core.market_regime',
    'core.sector_scorer', 'core.breakout_stage',
    'scanner.universe', 'scanner.batch_runner', 'scanner.report',
    'backtest.engine', 'backtest.metrics'
]
for m in modules:
    try:
        __import__(m)
        print(f'  ✅ {m}')
    except Exception as e:
        print(f'  ❌ {m}: {e}')
print('验证完成')
"
```

**期望输出：** 所有模块 ✅

### 步骤 7：配置 Cron（自动扫描）

#### 7a. 编辑 crontab

```bash
crontab -e
```

#### 7b. 添加 Buy Stop 计划任务

```bash
# 每周一至周五 15:30，全市场扫描
30 15 * * 1-5 cd /Users/a1-6/Atlas-Trading-Agent && \
  bash buy_stop_v3/run_daily.sh --stocks 0 >> \
  buy_stop_v3/logs/cron.log 2>&1

# 每周一至周五 15:45，全市场 + 基本面扫描
45 15 * * 1-5 cd /Users/a1-6/Atlas-Trading-Agent && \
  bash buy_stop_v3/run_daily.sh --stocks 0 --fundamental >> \
  buy_stop_v3/logs/cron_fund.log 2>&1
```
```
```

#### 7c. 添加 Alibaba Risk Monitor 计划任务（可选）

```bash
# 每 15 分钟：价格/成交量异常监控（交易时段）
*/15 9-23 * * 1-5 cd /Users/a1-6/Atlas-Trading-Agent && \
  source venv/bin/activate && \
  python3 alibaba_risk_monitor/alibaba_risk_monitor.py --price >> \
  alibaba_risk_monitor/logs/cron_price.log 2>&1

# 每 30 分钟：综合扫描（法律+新闻）
*/30 9-23 * * 1-5 cd /Users/a1-6/Atlas-Trading-Agent && \
  source venv/bin/activate && \
  python3 alibaba_risk_monitor/alibaba_risk_monitor.py --all >> \
  alibaba_risk_monitor/logs/cron_comprehensive.log 2>&1
```
```

#### 7d. 验证 cron

```bash
crontab -l
# → 显示所有已配置的任务

# 验证脚本权限
ls -la buy_stop_v3/run_daily.sh
# → -rwxr-xr-x  (有执行权限)
```

### 步骤 8：创建必要的目录

```bash
cd ~/Atlas-Trading-Agent
mkdir -p buy_stop_v3/output/json
mkdir -p buy_stop_v3/output/reports
mkdir -p buy_stop_v3/logs
mkdir -p buy_stop_v3/data/.cache
mkdir -p alibaba_risk_monitor/output
mkdir -p alibaba_risk_monitor/logs
```

### 步骤 9：运行验证

#### 9a. 快速扫描测试

```bash
cd ~/Atlas-Trading-Agent
source venv/bin/activate
export PYTHONPATH="$PWD/buy_stop_v3:$PYTHONPATH"

# 扫描前 10 只股票
python3 buy_stop_v3/run_scan.py --stocks 10

# 预期输出：
# Buy Stop V3 扫描启动
#   ...
# Buy Stop V3 扫描完成
```

#### 9b. 验证报告生成

```bash
ls -la buy_stop_v3/output/json/
ls -la buy_stop_v3/output/reports/
```

#### 9c. 验证日志

```bash
cat buy_stop_v3/logs/buy_stop.log | tail -5
```

### 步骤 10：最终验证

```bash
cd ~/Atlas-Trading-Agent
source venv/bin/activate

# 10a. 验证版本
git log --oneline -1
git tag -l

# 10b. 验证 Git 状态
git status
# → clean

# 10c. 验证 cron 任务
crontab -l

# 10d. 验证环境变量
echo $WECOM_WEBHOOK_URL | head -c 30
# → https://qyapi.weixin.qq.com...
```

---

## 四、历史数据恢复

### 信号历史 CSV

```bash
# 如果旧的 signal_history.csv 有备份
cp ~/backup/signal_history.csv ~/Atlas-Trading-Agent/buy_stop_v3/output/signal_history.csv
```

### 缓存数据

```bash
# 缓存会自动重建，无需恢复
# 首次运行时，缓存为空不影响功能
```

### 日志数据

```bash
# 日志从新开始，旧日志在备份中
tar -czf ~/backup_logs_$(date +%Y%m%d).tar.gz ~/Atlas-Trading-Agent/buy_stop_v3/logs/
```

---

## 五、故障排除

### 问题 1：模块导入失败

```
❌ core.screener: No module named 'xxx'
```

**解决：**
```bash
# 确认 PYTHONPATH 正确
echo $PYTHONPATH
# → .../Atlas-Trading-Agent/buy_stop_v3

# 如果为空
export PYTHONPATH="$HOME/Atlas-Trading-Agent/buy_stop_v3"
```

### 问题 2：扫描时报 SSL 错误

```
requests.exceptions.SSLError ...
```

**解决：** 本项目使用 curl 子进程，默认不依赖 Python SSL 栈。确认 `curl` 已安装：
```bash
curl --version
```

### 问题 3：企业微信推送失败

```
企业微信推送网络错误
```

**解决：**
```bash
# 确认 Webhook URL 正确
echo $WECOM_WEBHOOK_URL | head -c 40
# 测试网络
curl -s "$WECOM_WEBHOOK_URL" -H "Content-Type: application/json" \
  -d '{"msgtype":"text","text":{"content":"测试消息"}}'
```

### 问题 4：扫描无候选输出

```
候选数量：0
```

**说明：** 这是正常现象。Buy Stop 策略在震荡市或熊市中候选极少。运行 `--stocks 0` 全市场扫描确认。

### 问题 5: cron 不执行

```bash
# 检查 cron 日志
grep -i "error\|fail" buy_stop_v3/logs/cron.log

# 手动测试脚本
bash buy_stop_v3/run_daily.sh --stocks 10

# 确认 cron 在运行
pgrep cron
# → 有 PID 输出
```

### 问题 6: Alibaba Risk Monitor 法律监控失败

**解决：** 确认已注册 CourtListener 并设置 Token。如未设置，RSS 备选方案会自动降级。

---

## 六、恢复完成确认清单

- [ ] Python 3.10+ 已安装
- [ ] 仓库已克隆到 `~/Atlas-Trading-Agent/`
- [ ] 虚拟环境已创建并激活
- [ ] `requirements.txt` 已安装
- [ ] `WECOM_WEBHOOK_URL` 已设置
- [ ] 所有核心模块导入成功（步骤 6）
- [ ] `crontab` 已配置 Buy Stop 定时扫描
- [ ] `run_scan.py —stocks 10` 运行正常
- [ ] `output/` 目录有报告文件
- [ ] `logs/` 目录有日志文件
- [ ] Git 工作区 clean
- [ ] `git tag v3.4-production` 存在

---

> 本文件由 Atlas Trading Agent 自动生成，确保任何 AI 或开发者都能独立完成系统恢复。

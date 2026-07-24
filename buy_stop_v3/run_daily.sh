#!/bin/bash
# Buy Stop V3 — 无人值守扫描启动脚本
# 用法: bash run_daily.sh                   # 扫描前100只
# 用法: bash run_daily.sh --stocks 0        # 全市场
# 用法: bash run_daily.sh --market HS300    # 沪深300
#
# 可配合 cron 每日收盘后运行：
#   30 15 * * 1-5 /Users/a1-6/buy_stop_v3/run_daily.sh --stocks 0 >> /Users/a1-6/buy_stop_v3/logs/cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 日志
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/daily_scan_${TIMESTAMP}.log"

# Python 环境
ACTIVATE="${SCRIPT_DIR}/venv/bin/activate"
if [ -f "$ACTIVATE" ]; then
    source "$ACTIVATE"
else
    # 回退到 Hermes venv
    source /Users/a1-6/.hermes/hermes-agent/venv/bin/activate
fi

# 参数
ARGS="${*:---stocks 100}"

echo "============================================" | tee -a "$LOG_FILE"
echo "Buy Stop V3 每日扫描" | tee -a "$LOG_FILE"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "参数: $ARGS" | tee -a "$LOG_FILE"
echo "============================================" | tee -a "$LOG_FILE"

# 执行扫描（所有输出同时写入日志和终端）
PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH" \
    python3 run_scan.py $ARGS 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo "扫描完成: 退出码 $EXIT_CODE" | tee -a "$LOG_FILE"
else
    echo "扫描异常: 退出码 $EXIT_CODE" | tee -a "$LOG_FILE"
fi

echo "日志: $LOG_FILE"
exit $EXIT_CODE

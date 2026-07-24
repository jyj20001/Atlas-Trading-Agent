#!/bin/bash
# Buy Stop V3 — 使用 Hermes venv 运行
source /Users/a1-6/.hermes/hermes-agent/venv/bin/activate
cd /Users/a1-6/buy_stop_v3
PYTHONPATH="/Users/a1-6/buy_stop_v3:$PYTHONPATH" exec python3 "$@"

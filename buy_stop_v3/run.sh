#!/bin/bash
# Buy Stop V3 — 便捷运行（自动探测目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
if [ -f "${SCRIPT_DIR}/venv/bin/activate" ]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
fi
PYTHONPATH="${SCRIPT_DIR}:$PYTHONPATH" exec python3 "$@"

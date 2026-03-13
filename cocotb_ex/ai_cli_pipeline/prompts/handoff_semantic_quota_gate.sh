#!/bin/bash
set -euo pipefail

SEMANTIC_REVIEW_REQUEST="{semantic_review_request}"
SEMANTIC_REVIEW_MODE="{semantic_review_mode_value}"

mode=$(printf '%s' "$SEMANTIC_REVIEW_MODE" | tr '[:upper:]' '[:lower:]')
if [[ "$mode" == "off" ]]; then
    echo "[HANDOFF][OK] semantic quota gate skipped: semantic_review_mode=off"
    exit 0
fi

if [[ "${{CHIPFLOW_SKIP_QUOTA_GUARD:-0}}" == "1" ]]; then
    echo "[HANDOFF][OK] semantic quota gate skipped: CHIPFLOW_SKIP_QUOTA_GUARD=1"
    exit 0
fi

if [[ -z "$SEMANTIC_REVIEW_REQUEST" || ! -f "$SEMANTIC_REVIEW_REQUEST" ]]; then
    echo "[HANDOFF][OK] semantic quota gate skipped: no semantic review request"
    exit 0
fi

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[HANDOFF][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" ../tools/pre_task_quota_guard.py

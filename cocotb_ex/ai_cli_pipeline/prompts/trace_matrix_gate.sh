#!/bin/bash
set -euo pipefail

MATRIX_JSON="{matrix_json}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[TRACE_GATE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/trace_matrix_gate.py \
    --input "$MATRIX_JSON" \
    --max-no-testplan 0 \
    --max-missing-test-impl 0 \
    --max-no-signal-link 0 \
    --min-ok-rate 1.0

echo "[TRACE_GATE][OK] CI gate passed"

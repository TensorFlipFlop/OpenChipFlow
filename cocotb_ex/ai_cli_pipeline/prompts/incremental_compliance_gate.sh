#!/bin/bash
set -euo pipefail

CONTEXT="{handoff_context}"
OUT_JSON="{out_json}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[COMPLIANCE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" ../tools/incremental_compliance_gate.py \
    --context "$CONTEXT" \
    --workspace . \
    --out "$OUT_JSON"

echo "[COMPLIANCE][OK] incremental scope checked"

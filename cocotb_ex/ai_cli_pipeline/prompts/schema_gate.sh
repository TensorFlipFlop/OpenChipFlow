#!/bin/bash
set -euo pipefail

INPUT_JSON="{input_json}"
SCHEMA_JSON="{schema_json}"
LABEL="{label}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[SCHEMA_GATE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/schema_gate.py \
    --input "$INPUT_JSON" \
    --schema "$SCHEMA_JSON" \
    --label "$LABEL"

echo "[SCHEMA_GATE][OK] $LABEL"

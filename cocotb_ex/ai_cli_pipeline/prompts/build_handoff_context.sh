#!/bin/bash
set -euo pipefail

MANIFEST="{handoff_manifest}"
OUTPUT="{handoff_context}"
EXPECTED_STATE="{delivery_state}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[HANDOFF][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" ../tools/build_handoff_context.py \
    --manifest "$MANIFEST" \
    --workspace . \
    --output "$OUTPUT" \
    --expect-state "$EXPECTED_STATE"

echo "[HANDOFF][OK] context built"

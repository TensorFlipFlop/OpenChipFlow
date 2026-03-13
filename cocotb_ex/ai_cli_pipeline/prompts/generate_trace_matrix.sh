#!/bin/bash
set -euo pipefail

REQS_FILE="{reqs_file}"
TESTPLAN_FILE="{testplan_file}"
TEST_FILE="{test_file}"
TB_WRAPPER_FILE="{tb_wrapper_file}"
RTL_FILE="{rtl_file}"
OUT_MD="{matrix_md}"
OUT_JSON="{matrix_json}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[TRACE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/generate_trace_matrix.py \
    --reqs "$REQS_FILE" \
    --testplan "$TESTPLAN_FILE" \
    --tests "$TEST_FILE" \
    --tb-wrapper "$TB_WRAPPER_FILE" \
    --rtl "$RTL_FILE" \
    --out-md "$OUT_MD" \
    --out-json "$OUT_JSON"

echo "[TRACE][OK] Generated trace matrix: $OUT_MD"

#!/bin/bash
set -euo pipefail

TESTPLAN="{testplan_file}"
SCHEDULE="{schedule_file}"
TESTS="{test_file}"
REPORT="{report_file}"

mkdir -p "$(dirname "$REPORT")"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[VALIDATE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

if ! "$PYTHON_BIN" tools/validate_testcases.py \
    --testplan "$TESTPLAN" \
    --schedule "$SCHEDULE" \
    --tests "$TESTS" \
    --report "$REPORT"; then
    echo "[VALIDATE][ERROR] Testcase validation failed. Report:" >&2
    cat "$REPORT" >&2 || true
    exit 1
fi

echo "[VALIDATE][OK] Testcase validation passed."

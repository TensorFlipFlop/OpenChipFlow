#!/bin/bash
set -euo pipefail

TESTPLAN="{testplan_file}"
SCHEDULE="{schedule_file}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[SCHEDULE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/build_case_schedule.py --testplan "$TESTPLAN" --output "$SCHEDULE"
echo "[SCHEDULE][OK] Wrote $SCHEDULE"

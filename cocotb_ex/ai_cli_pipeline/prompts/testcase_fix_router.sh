#!/bin/bash
set -euo pipefail

TESTPLAN="{testplan_file}"
SCHEDULE="{schedule_file}"
TESTS="{test_file}"
REPORT="{report_file}"
export REPORT

mkdir -p "$(dirname "$REPORT")"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[FIX][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/validate_testcases.py \
    --testplan "$TESTPLAN" \
    --schedule "$SCHEDULE" \
    --tests "$TESTS" \
    --report "$REPORT" || true

"$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

report_path = Path(os.environ.get("REPORT", "ai_cli_pipeline/verification/testcase_validation.json"))
if not report_path.exists():
    print("[FIX][WARN] Validation report not found; skipping auto-fix.")
    sys.exit(0)

report = json.loads(report_path.read_text(encoding="utf-8"))
issues = set(report.get("issues", []))

actions = []
def add(role):
    if role not in actions:
        actions.append(role)

if report.get("testplan_missing") or report.get("missing_testcase_column") or "empty_testcase_column" in issues:
    add("req_testplan_generator")
    add("dv_agent")
    add("case_schedule_builder")
else:
    if report.get("schedule_missing") or report.get("schedule_invalid"):
        add("case_schedule_builder")
    if report.get("missing_in_schedule") or report.get("missing_in_testplan"):
        add("case_schedule_builder")
    if report.get("tests_missing") or report.get("missing_in_tests") or report.get("missing_run_basic") or "no_tests_found" in issues:
        add("dv_agent")

if not actions:
    print("[FIX][INFO] No auto-fix actions selected.")
    sys.exit(0)

print("[FIX][INFO] Auto-fix actions:", ", ".join(actions))
for role in actions:
    cmd = [sys.executable, "ai_cli_pipeline/run_pipeline.py", "--role", role]
    print("[FIX][RUN]", " ".join(cmd))
    subprocess.run(cmd, check=False)
PY

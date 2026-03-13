#!/bin/bash
# 由 Pipeline 注入参数: {top_level}, {rtl_filelist}, {test_module}, {test_file}, {testcase}, {error_logs}

set -o pipefail

# Validate testcase exists to avoid silent empty runs
TESTCASE="{testcase}"
TEST_FILE="{test_file}"
if [ -n "$TESTCASE" ]; then
    if [ ! -f "$TEST_FILE" ]; then
        echo "[SIM][ERROR] $TEST_FILE not found; cannot validate testcase '$TESTCASE'." >&2
        exit 1
    fi
    export TESTCASE TEST_FILE
    PYTHON_BIN=""
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN=python3
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN=python
    else
        echo "[SIM][ERROR] python3/python not found on PATH." >&2
        exit 127
    fi
    "$PYTHON_BIN" - <<'PY'
import os
import re
import sys
from pathlib import Path

name = os.environ.get("TESTCASE", "")
path = Path(os.environ.get("TEST_FILE", ""))
text = path.read_text(encoding="utf-8")
tests = re.findall(r"^(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.M)
if not tests:
    sys.stderr.write("[SIM][ERROR] No test functions found in " + str(path) + "\\n")
    sys.exit(1)
try:
    regex = re.compile(name)
except re.error:
    regex = None
if regex:
    ok = any(regex.search(t) for t in tests)
else:
    ok = name in tests
if not ok:
    sys.stderr.write("[SIM][ERROR] Testcase '" + name + "' not found in " + str(path) + "\\n")
    sys.exit(1)
PY
fi

# 执行仿真并捕获日志
if make -C sim sim TOPLEVEL="{top_level}" RTL_FILELISTS="{rtl_filelist}" COCOTB_TEST_MODULES="{test_module}" COCOTB_TESTCASE="{testcase}" WAVES=0 COV=0 2>&1 | tee "{error_logs}"; then
    rm -f "{error_logs}"
    echo "SIM_PASS"
else
    echo "SIM_FAIL"
fi

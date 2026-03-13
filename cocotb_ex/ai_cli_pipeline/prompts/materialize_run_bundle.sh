#!/bin/bash
set -euo pipefail

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[RUN_BUNDLE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" tools/materialize_run_bundle.py \
    --workspace . \
    --run-id "{timestamp}" \
    --out-root "artifacts/runs" \
    --inbox-spec "{inbox_spec_file}" \
    --spec "{spec_file}" \
    --reqs "{reqs_file}" \
    --testplan "{testplan_file}" \
    --rtl "{rtl_file}" \
    --tb-wrapper "{tb_wrapper_file}" \
    --tb-py "{tb_py_file}" \
    --tests "{test_file}" \
    --verify-report "{verify_report}" \
    --trace-md "{matrix_md}" \
    --trace-json "{matrix_json}"

echo "[RUN_BUNDLE][OK] snapshot generated"

#!/bin/bash
set -euo pipefail

WORKFLOW="{workflow}"
CONTRACT_JSON="{contract_json}"
LOG_DIR="{log_dir}"
TIMESTAMP="{timestamp}"
OUT_JSON="{out_json}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[MUST_CALL_GATE][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]:-$0}}")" && pwd)"
PIPELINE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# This prompt is usually piped into `bash` (not executed as a file), so BASH_SOURCE
# may not point to this script path. Resolve must_call_gate.py via a small candidate set.
CANDIDATES=(
    "$PWD/tools/must_call_gate.py"
    "$PWD/../tools/must_call_gate.py"
    "$PWD/../../tools/must_call_gate.py"
    "$PIPELINE_DIR/../../tools/must_call_gate.py"
)

GATE_PY=""
for c in "${{CANDIDATES[@]}}"; do
    if [[ -f "$c" ]]; then
        GATE_PY="$c"
        break
    fi
done

if [[ -z "$GATE_PY" ]]; then
    echo "[MUST_CALL_GATE][ERROR] gate script not found. tried:" >&2
    printf '  - %s\n' "${{CANDIDATES[@]}}" >&2
    exit 2
fi

"$PYTHON_BIN" "$GATE_PY" \
    --contract "$CONTRACT_JSON" \
    --workspace . \
    --log-dir "$LOG_DIR" \
    --workflow "$WORKFLOW" \
    --timestamp "$TIMESTAMP" \
    --out "$OUT_JSON"

echo "[MUST_CALL_GATE][OK] $WORKFLOW"

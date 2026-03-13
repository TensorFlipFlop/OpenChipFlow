#!/bin/bash
set -euo pipefail

HANDOFF_ROOT="{handoff_root}"
HANDOFF_MANIFEST="{handoff_manifest}"
SOURCE_REQUIREMENTS_ROOT="{source_requirements_root}"
SEMANTIC_REVIEW_MODE="{semantic_review_mode_value}"
TARGET_STATE="{target_state}"
OUT_DIR="{out_dir}"
SESSION_ROOT="{session_root}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[HANDOFF][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

set -- ../tools/handoff_intake_validator.py --workspace . --target-state "$TARGET_STATE" --out-dir "$OUT_DIR"
if [[ -n "$HANDOFF_ROOT" ]]; then
    set -- "$@" --handoff-root "$HANDOFF_ROOT"
fi
if [[ -n "$HANDOFF_MANIFEST" ]]; then
    set -- "$@" --manifest "$HANDOFF_MANIFEST"
fi
if [[ -n "$SOURCE_REQUIREMENTS_ROOT" ]]; then
    set -- "$@" --source-requirements-root "$SOURCE_REQUIREMENTS_ROOT"
fi
if [[ -n "$SEMANTIC_REVIEW_MODE" ]]; then
    set -- "$@" --semantic-review-mode "$SEMANTIC_REVIEW_MODE"
fi
if [[ -n "$SESSION_ROOT" ]]; then
    set -- "$@" --session-root "$SESSION_ROOT"
fi

set +e
"$PYTHON_BIN" "$@"
RC=$?
set -e
if [[ $RC -ne 0 ]]; then
    if [[ -f "$OUT_DIR/handoff_gap_report.md" ]]; then
        echo "[HANDOFF][SUMMARY] intake gap report:"
        sed -n '1,160p' "$OUT_DIR/handoff_gap_report.md"
    fi
    if [[ $RC -eq 1 && -f "$OUT_DIR/handoff_contract_audit.json" ]]; then
        echo "[HANDOFF][INFO] intake reported needs_repair; continuing so downstream semantic review / acceptance can run"
        exit 0
    fi
    exit "$RC"
fi

echo "[HANDOFF][OK] intake validator finished"

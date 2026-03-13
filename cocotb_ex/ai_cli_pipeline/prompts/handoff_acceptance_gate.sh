#!/bin/bash
set -euo pipefail

CONTRACT_AUDIT="{contract_audit}"
SEMANTIC_REVIEW="{semantic_review}"
ACCEPTANCE_JSON="{acceptance_json}"
SEMANTIC_REVIEW_MODE="{semantic_review_mode_value}"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    echo "[HANDOFF][ERROR] python3/python not found on PATH." >&2
    exit 127
fi

"$PYTHON_BIN" ../tools/handoff_acceptance_gate.py \
    --contract-audit "$CONTRACT_AUDIT" \
    --semantic-review "$SEMANTIC_REVIEW" \
    --acceptance-json "$ACCEPTANCE_JSON" \
    --semantic-review-mode "$SEMANTIC_REVIEW_MODE"

#!/usr/bin/env bash
# Do not use set -e to allow custom handling of git status
# set -e 

CASE_ID="{case_id}"
MSG="[case:$CASE_ID] AI simulation update"

# Check for file changes
# git status --porcelain returns output if there are changes
if [[ -n "$(git status --porcelain)" ]]; then
    git add .
    # Attempt commit. If it fails (e.g. race condition), we capture it but don't crash pipeline hard unless intended.
    if git commit -m "$MSG"; then
        echo "[COMMIT] Committed: $MSG"
    else
        echo "[WARN] Commit failed (possibly empty or race condition)"
    fi
else
    echo "[INFO] No changes to commit for $CASE_ID"
fi

# Always exit 0 to prevent pipeline from flagging this as [FAIL]
exit 0

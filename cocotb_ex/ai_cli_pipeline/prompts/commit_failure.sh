#!/usr/bin/env bash
set -euo pipefail

SUMMARY_FILE="{summary_file}"
CASE_ID="{case_id}"

if [[ ! -f "$SUMMARY_FILE" ]]; then
  echo "[commit] missing summary: $SUMMARY_FILE"
  exit 0
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "[commit] not a git repo"
  exit 0
fi

if ! git config user.name >/dev/null; then
  echo "[commit] git user.name not set; skip commit"
  exit 0
fi

if ! git config user.email >/dev/null; then
  echo "[commit] git user.email not set; skip commit"
  exit 0
fi

if [[ -n "$(git diff --cached --name-only)" ]]; then
  echo "[commit] staged changes exist; skip commit"
  exit 0
fi

# 1. Stage the summary file (Protect it from checkout/clean)
git add "$SUMMARY_FILE"

# 2. Discard all other changes (The failed fix attempts)
# Revert modified tracked files
git checkout .
# Remove untracked files (excluding staged ones)
git clean -fd

# 3. Check if we still have the summary staged
if git diff --cached --quiet; then
  echo "[commit] nothing to commit (summary lost?)"
  exit 0
fi

git commit -m "sim failure $CASE_ID: summary (discarded failed fixes)"

#!/bin/bash
set -e

# Repository Root Resolution
# The script is executed from the Workspace Anchor (cocotb_ex)
# But git commands should run at the repo root.
REPO_ROOT=$(git rev-parse --show-toplevel)

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M)
BRANCH_NAME="dev_$TIMESTAMP"

# Check if we are already on a dev branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" == dev_* ]]; then
    echo "BRANCH_OK: Already on $CURRENT_BRANCH"
    exit 0
fi

# Create and switch to new branch
echo "Creating branch $BRANCH_NAME..."
git checkout -b "$BRANCH_NAME"

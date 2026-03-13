#!/bin/bash
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_DIR="archive/run_${TIMESTAMP}"
mkdir -p "${ARCHIVE_DIR}"
echo "Created archive directory: ${ARCHIVE_DIR}"

# Helper to archive a directory by MOVING it (for results/logs)
archive_dir() {
    SRC=$1
    DEST_REL=$2
    if [ -d "$SRC" ]; then
        mkdir -p "$(dirname "${ARCHIVE_DIR}/${DEST_REL}")"
        echo "Moving $SRC to archive..."
        mv "$SRC" "${ARCHIVE_DIR}/${DEST_REL}"
        # Remove .gitkeep from archive if it exists (artifacts don't need placeholders)
        rm -f "${ARCHIVE_DIR}/${DEST_REL}/.gitkeep"
        # Recreate empty directory and maintain .gitkeep
        mkdir -p "$SRC"
        touch "$SRC/.gitkeep"
    else
        echo "Directory $SRC not found, skipping move."
    fi
}

# Helper to backup a directory by COPYING it, then CLEANING files (for source)
backup_source() {
    SRC=$1
    DEST_REL=$2
    if [ -d "$SRC" ]; then
        mkdir -p "$(dirname "${ARCHIVE_DIR}/${DEST_REL}")"
        echo "Backing up source $SRC (copying)..."
        # Copy while excluding __pycache__
        rsync -a --exclude='__pycache__' "$SRC/" "${ARCHIVE_DIR}/${DEST_REL}"
        # Remove .gitkeep from archive if it exists
        rm -f "${ARCHIVE_DIR}/${DEST_REL}/.gitkeep"
        # Clean files but keep structure and .gitkeep
        echo "Cleaning source files in $SRC..."
        find "$SRC" -type f ! -name ".gitkeep" -delete
    else
        echo "Source directory $SRC not found, skipping backup."
    fi
}

# Helper to backup a directory by COPYING it (Snapshot only, NO deletion)
snapshot_dir() {
    SRC=$1
    DEST_REL=$2
    if [ -d "$SRC" ]; then
        mkdir -p "$(dirname "${ARCHIVE_DIR}/${DEST_REL}")"
        echo "Snapshotting source $SRC (copying only)..."
        rsync -a --exclude='__pycache__' "$SRC/" "${ARCHIVE_DIR}/${DEST_REL}"
        # Remove .gitkeep from archive if it exists
        rm -f "${ARCHIVE_DIR}/${DEST_REL}/.gitkeep"
    else
        echo "Source directory $SRC not found, skipping snapshot."
    fi
}

# 1. Results (Move)
archive_dir "cocotb_ex/sim/out" "cocotb_ex/sim/out"
archive_dir "cocotb_ex/sim/regression_out" "cocotb_ex/sim/regression_out"

# 2. Source Code Snapshot (Copy then Clean)
backup_source "cocotb_ex/rtl" "cocotb_ex/rtl"
backup_source "cocotb_ex/tb" "cocotb_ex/tb"
backup_source "cocotb_ex/tests" "cocotb_ex/tests"
backup_source "cocotb_ex/filelists" "cocotb_ex/filelists"

# 3. Pipeline Logs & Artifacts (Move)
archive_dir "cocotb_ex/ai_cli_pipeline/logs" "cocotb_ex/ai_cli_pipeline/logs"
archive_dir "cocotb_ex/ai_cli_pipeline/specs/out" "cocotb_ex/ai_cli_pipeline/specs/out"
archive_dir "cocotb_ex/ai_cli_pipeline/verification" "cocotb_ex/ai_cli_pipeline/verification"

# 4. Inputs (Snapshot Only)
snapshot_dir "cocotb_ex/ai_cli_pipeline/specs/inbox" "cocotb_ex/ai_cli_pipeline/specs/inbox"

# 5. Cleanup non-archived items (sim_build)
if [ -d "cocotb_ex/sim/sim_build" ]; then
    echo "Cleaning sim_build (no archive)..."
    rm -rf cocotb_ex/sim/sim_build/*
    touch cocotb_ex/sim/sim_build/.gitkeep
fi

# 6. Cocotb Ex Artifacts (Global artifacts)
# archive_dir "cocotb_ex/artifacts" "cocotb_ex/artifacts"
# Commented out pending verification of contents

echo "Done. Archived to ${ARCHIVE_DIR}"
ls -R "${ARCHIVE_DIR}"

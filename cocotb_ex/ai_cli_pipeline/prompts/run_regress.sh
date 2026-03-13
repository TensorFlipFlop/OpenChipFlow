#!/bin/bash
# Parameters injected by Pipeline: {top_level}, {rtl_filelist}, {regr_modules}, {regr_seeds}, {regr_out}, {error_logs}

set -o pipefail

echo "Starting regression runner..."
echo "Target: {top_level}"
echo "Modules: {regr_modules}"

# Execute regression test and capture logs
if make -C sim regress TOPLEVEL="{top_level}" RTL_FILELISTS="{rtl_filelist}" REGR_MODULES="{regr_modules}" REGR_SEEDS="{regr_seeds}" REGR_OUT="{regr_out}" WAVES=0 COV=0 2>&1 | tee "{error_logs}"; then
    echo "Make returned 0 (Success)"
    # Remove log file if regression passed to keep things clean.
    rm -f "{error_logs}"
    echo "REGRESS_PASS"
else
    echo "Make returned non-zero (Failure)"
    echo "REGRESS_FAIL"
    # Ensure Pipeline detects the failure
    exit 1
fi

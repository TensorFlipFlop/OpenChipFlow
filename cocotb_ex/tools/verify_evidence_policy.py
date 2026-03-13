#!/usr/bin/env python3
"""
Evidence First Policy Verifier

Ensures that a run decision is backed by machine-readable artifacts.
"""
import sys
import os
import json
import argparse
from pathlib import Path

REQUIRED_ARTIFACTS = [
    "manifest.json",
    "trace_matrix.json"
]

def verify_evidence(run_id, artifacts_root):
    run_dir = Path(artifacts_root) / "runs" / run_id
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}")
        return False

    missing = []
    for artifact in REQUIRED_ARTIFACTS:
        p = run_dir / artifact
        if not p.exists():
            missing.append(artifact)
        elif p.stat().st_size == 0:
            missing.append(f"{artifact} (empty)")

    if missing:
        print(f"FAIL: Missing required evidence for run {run_id}: {', '.join(missing)}")
        print("Violation of 'Evidence First' policy: Decisions must be backed by structured artifacts.")
        return False

    # Optional: Basic schema validation or content check could be added here
    print(f"PASS: Evidence verified for run {run_id}. Found: {', '.join(REQUIRED_ARTIFACTS)}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify compliance with Evidence First Policy")
    parser.add_argument("--run-id", required=True, help="Run ID to verify")
    parser.add_argument("--artifacts-root", default="artifacts", help="Root artifacts directory")
    args = parser.parse_args()

    success = verify_evidence(args.run_id, args.artifacts_root)
    sys.exit(0 if success else 1)

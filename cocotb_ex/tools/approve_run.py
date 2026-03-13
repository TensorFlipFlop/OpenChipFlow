#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime

def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))

def main():
    parser = argparse.ArgumentParser(description="Record a Human-In-The-Loop (HITL) approval")
    parser.add_argument("--run-id", required=True, help="Run ID associated with the approval")
    parser.add_argument("--approver", required=True, help="Name/ID of the approver")
    parser.add_argument("--reason", required=True, help="Justification for approval")
    parser.add_argument("--action", required=True, choices=["relax_threshold", "skip_stage", "merge_known_fail", "other"], help="Type of action approved")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    args = parser.parse_args()

    workspace = expand_path(args.workspace)
    log_file = os.path.join(workspace, "artifacts", "approvals", "approval_log.jsonl")
    
    # Ensure dir exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    record = {
        "schema_version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "run_id": args.run_id,
        "approver": args.approver,
        "action": args.action,
        "reason": args.reason
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[APPROVAL] Recorded: {record['action']} by {record['approver']}")
        print(f"[LOG] {log_file}")
    except Exception as e:
        print(f"[FAIL] Could not write to approval log: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

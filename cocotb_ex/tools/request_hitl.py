#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime


def expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a pending HITL escalation request")
    parser.add_argument("--run-id", required=True, help="Run ID associated with the failure")
    parser.add_argument("--stage", required=True, help="Failing stage/role")
    parser.add_argument("--reason", required=True, help="Escalation reason")
    parser.add_argument("--escalation-packet", default="", help="Path to generated escalation packet")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    args = parser.parse_args()

    workspace = expand_path(args.workspace)
    out_file = os.path.join(workspace, "artifacts", "approvals", "pending_hitl_requests.jsonl")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    record = {
        "schema_version": "1.0",
        "requested_at": datetime.now().isoformat(),
        "status": "PENDING_HITL",
        "run_id": args.run_id,
        "stage": args.stage,
        "reason": args.reason,
        "escalation_packet": args.escalation_packet,
    }

    with open(out_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[HITL] Pending request recorded: {out_file}")
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

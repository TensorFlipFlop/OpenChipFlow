#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import re
from datetime import datetime

def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))

def get_git_diff(workspace):
    try:
        # Check staged and unstaged changes
        res = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=workspace, capture_output=True, text=True
        )
        if res.returncode == 0:
            return res.stdout.splitlines()
        return []
    except Exception:
        return []

def read_log_content(log_path, max_lines=500):
    if not log_path or not os.path.exists(log_path):
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.readlines()
            return "".join(content[-max_lines:])
    except Exception:
        return None

def load_error_catalog(workspace):
    # Try workspace relative path first
    catalog_path = os.path.join(workspace, "cocotb_ex", "config", "error_catalog.json")
    if not os.path.exists(catalog_path):
        # Fallback to script relative path
        script_dir = os.path.dirname(os.path.abspath(__file__))
        catalog_path = os.path.join(script_dir, "..", "config", "error_catalog.json")
    
    if os.path.exists(catalog_path):
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def analyze_log(log_content, catalog):
    analysis = {
        "matched_errors": [],
        "suggested_actions": [],
        "categories": set()
    }
    if not log_content or not catalog:
        return analysis

    for err in catalog.get("errors", []):
        pattern = err.get("pattern")
        if pattern and re.search(pattern, log_content, re.IGNORECASE):
            analysis["matched_errors"].append({
                "code": err.get("code"),
                "description": err.get("description"),
                "category": err.get("category", "UNKNOWN")
            })
            if err.get("category"):
                analysis["categories"].add(err.get("category"))
            if err.get("suggested_action"):
                analysis["suggested_actions"].append(err.get("suggested_action"))
    
    analysis["suggested_actions"] = list(set(analysis["suggested_actions"]))
    analysis["categories"] = list(analysis["categories"]) # Convert to list for JSON serialization
    return analysis

def main():
    parser = argparse.ArgumentParser(description="Generate escalation packet for HITL handoff")
    parser.add_argument("--run-id", required=True, help="Current run ID")
    parser.add_argument("--stage", required=True, help="Failing stage/role name")
    parser.add_argument("--log-file", help="Path to the log file of the failing stage")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--output", help="Output path for escalation packet JSON")
    args = parser.parse_args()

    workspace = expand_path(args.workspace)
    
    # 1. Read Log
    log_content = read_log_content(args.log_file)
    
    # 2. Load Catalog & Analyze
    catalog = load_error_catalog(workspace)
    diagnosis = analyze_log(log_content, catalog)

    # 3. Construct Packet
    packet = {
        "schema_version": "1.2",
        "type": "escalation_packet",
        "created_at": datetime.now().isoformat(),
        "run_id": args.run_id,
        "failing_stage": args.stage,
        "context": {
            "workspace": workspace,
            "git_changed_files": get_git_diff(workspace),
        },
        "failure_details": {
            "log_path": args.log_file,
            "log_tail": log_content[-1000:] if log_content else "(Log unavailable)",
            "diagnosis": diagnosis,
            "primary_category": diagnosis["categories"][0] if diagnosis["categories"] else "UNKNOWN"
        },
        "suggested_options": [
            "debug_interactively",
            "retry_with_stronger_model",
            "skip_stage (requires approval)",
            "relax_threshold (requires approval)"
        ]
    }

    # 4. Determine Output Path
    if args.output:
        out_path = args.output
    else:
        esc_dir = os.path.join(workspace, "artifacts", "escalations")
        os.makedirs(esc_dir, exist_ok=True)
        out_path = os.path.join(esc_dir, f"{args.run_id}_escalation.json")

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2)
        print(f"[ESCALATION] Packet generated: {out_path}")
        if diagnosis["matched_errors"]:
            print(f"[DIAGNOSIS] Detected: {[e['code'] for e in diagnosis['matched_errors']]}")
            print(f"[CATEGORY] {packet['failure_details']['primary_category']}")
    except Exception as e:
        print(f"[FAIL] Failed to write escalation packet: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

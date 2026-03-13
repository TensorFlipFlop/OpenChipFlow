#!/usr/bin/env python3
"""
Permission Policy Checker for OpenChipFlow Tools.

Enforces:
1. Allowlist-based execution (only approved tools can run).
2. Dangerous action approval (e.g., rm -rf, mkfs).
3. Timeout & Retry policy definitions per tool category.

Usage:
    python3 permission_policy_check.py --tool <tool_name> --args <args> [--dry-run]
"""

import sys
import argparse
import json
import re
import os

# --- Policy Configuration (Externalize this to a JSON file in production) ---
POLICY_CONFIG = {
    "allowlist": [
        "python3", "python", "make", "ls", "grep", "cat", "echo", "mkdir",
        "cp", "mv", "git", "iverilog", "vvp", "gtkwave",
        "cocotb-config", "pytest", "pylint"
    ],
    "dangerous_patterns": [
        r"rm\s+-[rf]+.*",      # Recursive force delete
        r"mkfs.*",             # Format filesystem
        r"dd\s+if=.*",         # Direct disk write
        r">:.*",               # Shell truncation (simplified)
        r"chmod\s+777.*"       # Permissive permissions
    ],
    "timeouts": {
        "simulation": 300,     # 5 minutes for sim
        "synthesis": 600,      # 10 minutes for synth
        "default": 30
    },
    "retries": {
        "network": 3,
        "io": 2,
        "default": 0
    }
}

def load_policy(policy_path="cocotb_ex/config/permission_policy.json"):
    """Loads policy from file if exists, else uses default."""
    if os.path.exists(policy_path):
        try:
            with open(policy_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"WARN: Failed to load policy file {policy_path}: {e}")
    return POLICY_CONFIG

def check_allowlist(tool_name, policy):
    """Checks if tool is in the allowlist."""
    # Simple check: is the command base name in the list?
    base_tool = tool_name.split()[0] # simplistic extraction
    if base_tool not in policy["allowlist"]:
        return False, f"Tool '{base_tool}' is not in the allowlist."
    return True, "OK"

def check_dangerous_args(args_str, policy):
    """Checks for dangerous argument patterns."""
    for pattern in policy["dangerous_patterns"]:
        if re.search(pattern, args_str):
            return False, f"Arguments match dangerous pattern: '{pattern}'"
    return True, "OK"

def get_timeout_policy(tool_category, policy):
    """Returns timeout for the tool category."""
    return policy["timeouts"].get(tool_category, policy["timeouts"]["default"])

def main():
    parser = argparse.ArgumentParser(description="OpenChipFlow Permission Policy Checker")
    parser.add_argument("--tool", required=True, help="Tool command/binary name")
    parser.add_argument("--args", default="", help="Arguments string")
    parser.add_argument("--category", default="default", help="Tool category for timeout/retry")
    parser.add_argument("--dry-run", action="store_true", help="Check only, do not block exit code (simulated)")
    
    args = parser.parse_args()
    
    policy = load_policy()
    
    # 1. Allowlist Check
    allowed, msg = check_allowlist(args.tool, policy)
    if not allowed:
        print(f"POLICY_VIOLATION: {msg}")
        if not args.dry_run:
            sys.exit(1)
            
    # 2. Dangerous Args Check
    full_cmd = f"{args.tool} {args.args}"
    
    safe, msg = check_dangerous_args(full_cmd, policy)
    if not safe:
        print(f"POLICY_VIOLATION: {msg}")
        if not args.dry_run:
            sys.exit(1)
            
    # 3. Policy Info (for wrapper to consume)
    timeout = get_timeout_policy(args.category, policy)
    retry = policy["retries"].get(args.category, policy["retries"]["default"])
    
    print(json.dumps({
        "status": "APPROVED",
        "tool": args.tool,
        "timeout_sec": timeout,
        "max_retries": retry
    }))

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Verify that critical gates fail closed (exit != 0) on violation.
Evidence for: "Fail-Closed: Critical gate fail implies process must fail-closed."
"""

import json
import subprocess
import sys
from pathlib import Path

def test_trace_gate_fail_closed():
    # Create a temporary failing matrix
    fail_matrix = {
        "summary": {
            "requirements": 1,
            "ok": 0,
            "no_testplan": 0,
            "missing_test_impl": 1,
            "no_signal_link": 0
        },
        "requirements": [
            {"req_id": "REQ-BAD", "status": "FAIL"}
        ]
    }
    
    tmp_json = Path("temp_fail_matrix.json")
    tmp_json.write_text(json.dumps(fail_matrix))
    
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent.parent
    gate_script = project_root / "cocotb_ex/tools/trace_matrix_gate.py"

    cmd = [
        sys.executable,
        str(gate_script),
        "--input", str(tmp_json.resolve()),
        "--min-ok-rate", "1.0"
    ]
    
    print(f"[TEST] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    tmp_json.unlink()
    
    if result.returncode == 0:
        print("[FAIL] trace_matrix_gate passed on bad input! (Fail-Open detected)")
        return False
    else:
        print(f"[PASS] trace_matrix_gate failed as expected (rc={result.returncode})")
        return True

def main():
    print("Verifying Fail-Closed behavior for critical gates...")
    if not test_trace_gate_fail_closed():
        sys.exit(1)
        
    print("All Fail-Closed checks passed.")

if __name__ == "__main__":
    main()

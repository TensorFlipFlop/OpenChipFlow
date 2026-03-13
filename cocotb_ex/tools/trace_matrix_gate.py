#!/usr/bin/env python3
"""CI gate for REQ->Testcase->RTL trace matrix.

Fails (exit 1) when matrix quality thresholds are violated.
Default policy is strict: all requirements must be status=OK.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Trace matrix quality gate")
    p.add_argument("--input", required=True, help="Path to req_trace_matrix.json")
    p.add_argument("--max-no-testplan", type=int, default=0)
    p.add_argument("--max-missing-test-impl", type=int, default=0)
    p.add_argument("--max-no-signal-link", type=int, default=0)
    p.add_argument("--min-ok-rate", type=float, default=1.0, help="minimum OK coverage ratio [0,1]")
    args = p.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"[TRACE_GATE][FAIL] matrix file missing: {path}")
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})

    total_reqs = int(summary.get("requirements", 0))
    ok_reqs = int(summary.get("ok", 0))
    no_testplan = int(summary.get("no_testplan", 0))
    missing_impl = int(summary.get("missing_test_impl", 0))
    no_signal = int(summary.get("no_signal_link", 0))
    ok_rate = (ok_reqs / total_reqs) if total_reqs > 0 else 0.0

    failed = False

    print("[TRACE_GATE] summary:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if no_testplan > args.max_no_testplan:
        print(
            f"[TRACE_GATE][FAIL] no_testplan={no_testplan} > max_no_testplan={args.max_no_testplan}"
        )
        failed = True

    if missing_impl > args.max_missing_test_impl:
        print(
            f"[TRACE_GATE][FAIL] missing_test_impl={missing_impl} > max_missing_test_impl={args.max_missing_test_impl}"
        )
        failed = True

    if no_signal > args.max_no_signal_link:
        print(
            f"[TRACE_GATE][FAIL] no_signal_link={no_signal} > max_no_signal_link={args.max_no_signal_link}"
        )
        failed = True

    if ok_rate < args.min_ok_rate:
        print(
            f"[TRACE_GATE][FAIL] ok_rate={ok_rate:.4f} < min_ok_rate={args.min_ok_rate:.4f}"
        )
        failed = True

    # Defensive check: verify no unexpected status in requirement rows
    reqs = data.get("requirements", [])
    bad_rows = [r.get("req_id", "?") for r in reqs if r.get("status") != "OK"]
    if bad_rows:
        print(f"[TRACE_GATE][FAIL] requirements with non-OK status: {', '.join(bad_rows)}")
        failed = True

    if failed:
        return 1

    print("[TRACE_GATE][OK] trace matrix gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

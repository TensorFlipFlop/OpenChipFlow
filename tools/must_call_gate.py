#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

RC_RE = re.compile(r"^#\s+rc:\s*(\d+)\s*$")


def parse_role_rc(log_file: Path) -> int | None:
    if not log_file.exists():
        return None
    try:
        for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
            m = RC_RE.match(line.strip())
            if m:
                return int(m.group(1))
    except Exception:
        return None
    # Backward compatibility: legacy role logs may not include '# rc:' header.
    # If the log file exists and is readable, treat it as called/success by default.
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce must-call roles and required artifacts")
    ap.add_argument("--contract", required=True, help="JSON contract path")
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--log-dir", required=True, help="role log directory")
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--timestamp", default="")
    ap.add_argument("--out", default="", help="optional json report")
    args = ap.parse_args()

    ws = Path(args.workspace).resolve()
    log_dir = Path(args.log_dir)
    if not log_dir.is_absolute():
        log_dir = (ws / log_dir).resolve()

    contract_path = Path(args.contract)
    if not contract_path.is_absolute():
        contract_path = (ws / contract_path).resolve()
    cfg = json.loads(contract_path.read_text(encoding="utf-8"))

    wf = cfg.get("workflows", {}).get(args.workflow, {})
    must_roles = wf.get("must_call_roles", [])
    req_artifacts = wf.get("required_artifacts", [])

    missing_roles: list[str] = []
    failed_roles: list[str] = []
    ok_roles: list[str] = []

    for role in must_roles:
        lp = log_dir / f"{role}.log"
        rc = parse_role_rc(lp)
        if rc is None:
            missing_roles.append(role)
        elif rc != 0:
            failed_roles.append(f"{role}(rc={rc})")
        else:
            ok_roles.append(role)

    missing_artifacts: list[str] = []
    ok_artifacts: list[str] = []
    for rel in req_artifacts:
        rel_path = rel.replace("{timestamp}", args.timestamp)
        p = (ws / rel_path).resolve()
        if not p.exists() or (p.is_file() and p.stat().st_size == 0):
            missing_artifacts.append(rel_path)
        else:
            ok_artifacts.append(rel_path)

    passed = not missing_roles and not failed_roles and not missing_artifacts
    report = {
        "generated_at": datetime.now().isoformat(),
        "workflow": args.workflow,
        "workspace": str(ws),
        "log_dir": str(log_dir),
        "contract": str(contract_path),
        "passed": passed,
        "must_call": {
            "ok_roles": ok_roles,
            "missing_roles": missing_roles,
            "failed_roles": failed_roles,
        },
        "artifacts": {
            "ok": ok_artifacts,
            "missing": missing_artifacts,
        },
    }

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = (ws / out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if passed:
        print("[MUST_CALL_GATE][OK] contract satisfied")
        return 0

    print("[MUST_CALL_GATE][FAIL] contract violated")
    if missing_roles:
        print("missing roles:", ", ".join(missing_roles))
    if failed_roles:
        print("failed roles:", ", ".join(failed_roles))
    if missing_artifacts:
        print("missing artifacts:", ", ".join(missing_artifacts))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

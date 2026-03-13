#!/usr/bin/env python3
"""Materialize run-level input/output snapshot bundle.

This creates a reproducible bundle under artifacts/runs/<run_id>/ with:
- inputs/
- derived/
- outputs/
- verification/
- manifest.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict


def main() -> int:
    p = argparse.ArgumentParser(description="Create run-level snapshot bundle")
    p.add_argument("--workspace", default=".")
    p.add_argument("--run-id", required=True)
    p.add_argument("--out-root", default="artifacts/runs")

    p.add_argument("--inbox-spec", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--reqs", required=True)
    p.add_argument("--testplan", required=True)

    p.add_argument("--rtl", required=True)
    p.add_argument("--tb-wrapper", required=True)
    p.add_argument("--tb-py", required=True)
    p.add_argument("--tests", required=True)

    p.add_argument("--verify-report", default="")
    p.add_argument("--trace-md", default="")
    p.add_argument("--trace-json", default="")
    p.add_argument("--dry-run", action="store_true", help="Do not write output files")
    p.add_argument("--strict", action="store_true", help="Fail if any expected file is missing")
    args = p.parse_args()

    root = Path(args.workspace).resolve()
    bundle_root = (root / args.out_root / args.run_id).resolve()
    if not args.dry_run:
        bundle_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "run_manifest/v1",
        "run_id": args.run_id,
        "created_at": datetime.now().isoformat(),
        "workspace": str(root),
        "inputs": {},
        "derived": {},
        "outputs": {},
        "verification": {},
    }

    def _process(rel_path: str, section: str):
        if not rel_path:
            return

        src = root / rel_path
        # Just resolve name, don't create path yet
        dst = bundle_root / section / Path(rel_path).name

        if not src.exists():
            if args.strict:
                raise FileNotFoundError(f"[STRICT] Missing required file: {src}")
            manifest[section][rel_path] = {"status": "missing"}
            if args.dry_run:
                print(f"[DRY-RUN] Would skip missing: {rel_path}")
            return

        if args.dry_run:
            print(f"[DRY-RUN] Would copy {src} -> {dst}")
            manifest[section][rel_path] = {
                "status": "would_copy",
                "snapshot": str(dst.relative_to(bundle_root)),
                "size": src.stat().st_size,
            }
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            manifest[section][rel_path] = {
                "status": "copied",
                "snapshot": str(dst.relative_to(bundle_root)),
                "size": src.stat().st_size,
            }

    _process(args.inbox_spec, "inputs")
    _process(args.spec, "derived")
    _process(args.reqs, "derived")
    _process(args.testplan, "derived")

    _process(args.rtl, "outputs")
    _process(args.tb_wrapper, "outputs")
    _process(args.tb_py, "outputs")
    _process(args.tests, "outputs")

    if args.verify_report:
        _process(args.verify_report, "verification")
    if args.trace_md:
        _process(args.trace_md, "verification")
    if args.trace_json:
        _process(args.trace_json, "verification")

    if args.dry_run:
        print("[DRY-RUN] Manifest preview:")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(f"[RUN_BUNDLE][DRY-RUN] Would create {bundle_root}")
    else:
        mf = bundle_root / "manifest.json"
        mf.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[RUN_BUNDLE][OK] {bundle_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

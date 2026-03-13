#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

LOG_HEADER_RE = re.compile(r"^#\s+(\w+):\s*(.*)$")


def parse_log(path: Path) -> dict:
    meta: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:12]:
        m = LOG_HEADER_RE.match(line)
        if not m:
            continue
        meta[m.group(1)] = m.group(2)
    return {
        "file": str(path),
        "stage": meta.get("stage", ""),
        "name": meta.get("name", ""),
        "cmd": meta.get("cmd", ""),
        "rc": int(meta.get("rc", "-1")) if meta.get("rc", "").isdigit() else -1,
        "duration_s": float(meta.get("duration_s", "0") or 0),
    }


def latest_run_dir(log_root: Path) -> Path | None:
    runs = sorted([p for p in log_root.glob("run_*") if p.is_dir()])
    return runs[-1] if runs else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Build run registry manifest from .runner_logs")
    ap.add_argument("--run-id", default="", help="run id, e.g. run_20260217_012504")
    ap.add_argument("--log-root", default=".runner_logs")
    ap.add_argument("--out-root", default="artifacts/runs")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    log_root = (root / args.log_root).resolve()
    if not log_root.exists():
        print(f"[ERR] log root not found: {log_root}")
        return 2

    run_dir = (log_root / args.run_id) if args.run_id else latest_run_dir(log_root)
    if not run_dir or not run_dir.exists():
        print("[ERR] run dir not found")
        return 2

    entries = []
    for p in sorted(run_dir.glob("*.log")):
        entries.append(parse_log(p))

    failed = [x for x in entries if x["rc"] != 0]
    manifest = {
        "run_id": run_dir.name,
        "generated_at": datetime.now().isoformat(),
        "log_root": str(log_root),
        "run_dir": str(run_dir),
        "commands": entries,
        "summary": {
            "total": len(entries),
            "failed": len(failed),
            "ok": len(failed) == 0,
        },
    }

    out_root = (root / args.out_root / run_dir.name)
    out_root.mkdir(parents=True, exist_ok=True)
    out = out_root / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] registry written: {out}")
    print(f"summary: total={manifest['summary']['total']} failed={manifest['summary']['failed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

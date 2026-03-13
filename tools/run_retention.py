#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunDir:
    path: Path
    run_id: str
    mtime: float


def load_milestones(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keep: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keep.add(line)
    return keep


def list_runs(runs_root: Path) -> list[RunDir]:
    out: list[RunDir] = []
    if not runs_root.exists():
        return out
    for p in runs_root.iterdir():
        if not p.is_dir() or not p.name.startswith("run_"):
            continue
        out.append(RunDir(path=p, run_id=p.name, mtime=p.stat().st_mtime))
    out.sort(key=lambda x: x.mtime, reverse=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Retention manager for run artifacts")
    ap.add_argument("--runs-root", default="artifacts/runs", help="run directory root")
    ap.add_argument("--keep-latest", type=int, default=10, help="keep latest N runs")
    ap.add_argument("--milestone-file", default="artifacts/runs/milestones.txt", help="run ids to keep forever")
    ap.add_argument("--out", default="", help="optional JSON plan/report output path")
    ap.add_argument("--apply", action="store_true", help="actually delete candidates (default dry-run)")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    runs_root = Path(args.runs_root)
    if not runs_root.is_absolute():
        runs_root = root / runs_root
    ms_file = Path(args.milestone_file)
    if not ms_file.is_absolute():
        ms_file = root / ms_file

    runs = list_runs(runs_root)
    milestones = load_milestones(ms_file)

    latest_ids = {r.run_id for r in runs[: max(0, args.keep_latest)]}
    keep: list[str] = []
    delete: list[str] = []

    for r in runs:
        if r.run_id in latest_ids or r.run_id in milestones:
            keep.append(r.run_id)
        else:
            delete.append(r.run_id)

    report = {
        "generated_at": datetime.now().isoformat(),
        "runs_root": str(runs_root),
        "milestone_file": str(ms_file),
        "mode": "apply" if args.apply else "dry-run",
        "total_runs": len(runs),
        "keep_latest": args.keep_latest,
        "milestones": sorted(milestones),
        "keep_count": len(keep),
        "delete_count": len(delete),
        "keep": keep,
        "delete": delete,
    }

    if args.apply:
        for rid in delete:
            shutil.rmtree(runs_root / rid, ignore_errors=False)

    out_path: Path | None = None
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "mode": report["mode"],
        "total_runs": report["total_runs"],
        "keep_count": report["keep_count"],
        "delete_count": report["delete_count"],
        "out": str(out_path) if out_path else "",
    }, ensure_ascii=False))
    if delete:
        print("delete candidates:")
        for rid in delete:
            print(f"- {rid}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

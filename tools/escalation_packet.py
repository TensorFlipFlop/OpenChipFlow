#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml


def latest(base: Path, pattern: str) -> Path | None:
    files = sorted(base.glob(pattern))
    return files[-1] if files else None


def read_text_safe(path: Path, max_lines: int = 160) -> str:
    if not path.exists() or not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[:max_lines])


def build_file_snapshot(root: Path, rel_path: str) -> dict:
    p = root / rel_path
    if not p.exists():
        return {"path": rel_path, "exists": False}
    text = p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
    return {
        "path": rel_path,
        "exists": True,
        "size": p.stat().st_size,
        "preview": "\n".join(text.splitlines()[:80]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build cleanroom escalation packet")
    ap.add_argument("--config", default="config/handoff_rules.yaml")
    ap.add_argument("--manifest", default="", help="run manifest path (default latest artifacts/runs/*/manifest.json)")
    ap.add_argument("--triage", default="", help="triage path (default latest artifacts/triage/*.json)")
    ap.add_argument("--decision", default="", help="sticky decision path (default latest artifacts/sticky/*.json)")
    ap.add_argument("--case-id", default="default")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / args.config).read_text(encoding="utf-8"))
    rules = cfg.get("cleanroom", {})

    manifest = Path(args.manifest) if args.manifest else latest(root, "artifacts/runs/run_*/manifest.json")
    triage = Path(args.triage) if args.triage else latest(root, "artifacts/triage/triage_*.json")
    decision = Path(args.decision) if args.decision else latest(root, "artifacts/sticky/decision_*.json")

    if manifest and not manifest.is_absolute():
        manifest = root / manifest
    if triage and not triage.is_absolute():
        triage = root / triage
    if decision and not decision.is_absolute():
        decision = root / decision

    manifest_obj = json.loads(manifest.read_text(encoding="utf-8")) if manifest and manifest.exists() else {}
    triage_obj = json.loads(triage.read_text(encoding="utf-8")) if triage and triage.exists() else {}
    decision_obj = json.loads(decision.read_text(encoding="utf-8")) if decision and decision.exists() else {}

    failed_logs = [x for x in manifest_obj.get("commands", []) if int(x.get("rc", -1)) != 0]
    max_lines = int(rules.get("max_log_excerpt_lines", 160))
    log_excerpt = []
    for f in failed_logs[:3]:
        fp = Path(f.get("file", ""))
        if not fp.is_absolute():
            fp = root / fp
        log_excerpt.append({
            "file": str(fp),
            "excerpt": read_text_safe(fp, max_lines=max_lines),
        })

    snapshots = [build_file_snapshot(root, p) for p in rules.get("include_files", [])]

    packet = {
        "generated_at": datetime.now().isoformat(),
        "case_id": args.case_id,
        "purpose": "cleanroom_escalation",
        "inputs": {
            "manifest": str(manifest) if manifest else "",
            "triage": str(triage) if triage else "",
            "decision": str(decision) if decision else "",
        },
        "decision": decision_obj,
        "triage_summary": triage_obj.get("summary", {}),
        "failed_logs": log_excerpt,
        "file_snapshots": snapshots,
        "taboo_list": rules.get("taboo_list", []),
    }

    out = Path(args.out) if args.out else root / "artifacts" / "handoff" / "escalation_packet.json"
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] escalation packet: {out}")
    print(json.dumps({"case_id": args.case_id, "snapshots": len(snapshots)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

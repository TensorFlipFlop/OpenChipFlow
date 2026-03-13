#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import yaml


def load_rules(path: Path) -> tuple[dict[str, list[str]], str]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    classes = cfg.get("classes", {})
    fallback = cfg.get("fallback", "UNKNOWN")
    return classes, fallback


def classify(text: str, classes: dict[str, list[str]], fallback: str) -> tuple[str, str]:
    low = text.lower()
    for cls, pats in classes.items():
        for p in pats:
            if p.lower() in low:
                return cls, p
    return fallback, ""


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_logs(entries: list[dict], classes: dict[str, list[str]], fallback: str) -> list[dict]:
    out = []
    for e in entries:
        f = Path(e.get("file", ""))
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        cls, hit = classify(text, classes, fallback)
        out.append(
            {
                "file": str(f),
                "stage": e.get("stage", ""),
                "name": e.get("name", ""),
                "rc": e.get("rc", -1),
                "class": cls,
                "matched_pattern": hit,
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify failed logs into normalized error classes")
    ap.add_argument("--rules", default="config/triage_rules.yaml")
    ap.add_argument("--manifest", default="", help="run manifest json path")
    ap.add_argument("--log", default="", help="single log path")
    ap.add_argument("--out", default="", help="output json path")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    rules_path = Path(args.rules)
    if not rules_path.is_absolute():
        rules_path = root / rules_path
    classes, fallback = load_rules(rules_path)

    results = []
    if args.log:
        lp = Path(args.log)
        if not lp.is_absolute():
            lp = root / lp
        text = lp.read_text(encoding="utf-8", errors="ignore")
        cls, hit = classify(text, classes, fallback)
        results = [{"file": str(lp), "class": cls, "matched_pattern": hit}]
    else:
        manifest_path = Path(args.manifest) if args.manifest else root / "artifacts" / "runs"
        if manifest_path.is_dir():
            # choose latest manifest
            manifests = sorted(manifest_path.glob("run_*/manifest.json"))
            if not manifests:
                print("[ERR] no manifest found")
                return 2
            manifest_path = manifests[-1]
        elif not manifest_path.is_absolute():
            manifest_path = root / manifest_path

        m = load_manifest(manifest_path)
        failed = [x for x in m.get("commands", []) if int(x.get("rc", -1)) != 0]
        results = classify_logs(failed, classes, fallback)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "results": results,
        "summary": {
            "total": len(results),
            "by_class": {},
        },
    }
    for r in results:
        payload["summary"]["by_class"].setdefault(r["class"], 0)
        payload["summary"]["by_class"][r["class"]] += 1

    out = args.out
    if not out:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = root / "artifacts" / "triage" / f"triage_{ts}.json"
    else:
        out = Path(out)
        if not out.is_absolute():
            out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] triage written: {out}")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

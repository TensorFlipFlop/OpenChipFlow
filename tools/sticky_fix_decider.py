#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml


def latest_file(glob_pat: str, base: Path) -> Path | None:
    files = sorted(base.glob(glob_pat))
    return files[-1] if files else None


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sticky-fix decision engine")
    ap.add_argument("--config", default="config/sticky_fix.yaml")
    ap.add_argument("--triage", default="", help="triage json path (default latest artifacts/triage)")
    ap.add_argument("--state", default="", help="state json path override")
    ap.add_argument("--out", default="", help="decision output path")
    ap.add_argument("--case-id", default="default")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    cfg_path = root / args.config if not Path(args.config).is_absolute() else Path(args.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    pol = cfg.get("policy", {})

    triage_path = Path(args.triage) if args.triage else latest_file("artifacts/triage/triage_*.json", root)
    if not triage_path:
        print("[ERR] no triage file found")
        return 2
    if not triage_path.is_absolute():
        triage_path = root / triage_path

    triage = load_json(triage_path, {})
    results = triage.get("results", [])
    if not results:
        decision = {
            "generated_at": datetime.now().isoformat(),
            "case_id": args.case_id,
            "triage": str(triage_path),
            "action": "NO_FAILURE",
            "reason": "No failed logs in triage",
        }
    else:
        classes = [r.get("class", "UNKNOWN") for r in results]
        primary = classes[0]

        state_path = Path(args.state) if args.state else root / cfg.get("state", {}).get("path", "artifacts/sticky/state.json")
        if not state_path.is_absolute():
            state_path = root / state_path
        state = load_json(state_path, {"cases": {}})
        case = state.setdefault("cases", {}).setdefault(args.case_id, {"logic_fail_streak": 0, "runtime_fail_streak": 0})

        sticky_set = set(pol.get("sticky_classes", []))
        logic_after = int(pol.get("logic_escalate_after", 2))
        runtime_after = int(pol.get("runtime_escalate_after", 2))

        action = "STICKY_FIX"
        reason = f"class={primary}"

        if primary == "LOGIC":
            case["logic_fail_streak"] = int(case.get("logic_fail_streak", 0)) + 1
            case["runtime_fail_streak"] = 0
            if case["logic_fail_streak"] >= logic_after:
                action = "ESCALATE"
                reason = f"LOGIC streak {case['logic_fail_streak']} >= {logic_after}"
        elif primary == "RUNTIME":
            case["runtime_fail_streak"] = int(case.get("runtime_fail_streak", 0)) + 1
            case["logic_fail_streak"] = 0
            if case["runtime_fail_streak"] >= runtime_after:
                action = "ESCALATE"
                reason = f"RUNTIME streak {case['runtime_fail_streak']} >= {runtime_after}"
        elif primary in sticky_set:
            case["logic_fail_streak"] = 0
            case["runtime_fail_streak"] = 0
            action = "STICKY_FIX"
            reason = f"{primary} is sticky class"
        elif primary == "INFRA":
            case["logic_fail_streak"] = 0
            case["runtime_fail_streak"] = 0
            action = "INFRA_RETRY"
            reason = "infrastructure failure"
        else:
            case["logic_fail_streak"] = 0
            case["runtime_fail_streak"] = 0
            action = "STICKY_FIX"
            reason = f"default sticky for class={primary}"

        save_json(state_path, state)

        decision = {
            "generated_at": datetime.now().isoformat(),
            "case_id": args.case_id,
            "triage": str(triage_path),
            "primary_class": primary,
            "all_classes": classes,
            "action": action,
            "reason": reason,
            "state_path": str(state_path),
            "state": state["cases"][args.case_id],
        }

    out = Path(args.out) if args.out else root / "artifacts" / "sticky" / f"decision_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if not out.is_absolute():
        out = root / out
    save_json(out, decision)

    print(f"[OK] decision written: {out}")
    print(json.dumps({"action": decision.get("action"), "reason": decision.get("reason")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

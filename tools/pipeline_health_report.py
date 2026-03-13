#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def list_recent_files(root: Path, pattern: str, since_ts: float) -> list[Path]:
    if not root.exists():
        return []
    files = []
    for p in sorted(root.glob(pattern)):
        try:
            if p.stat().st_mtime >= since_ts:
                files.append(p)
        except FileNotFoundError:
            continue
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="Build periodic pipeline health report")
    ap.add_argument("--runs-root", default="artifacts/runs")
    ap.add_argument("--sticky-root", default="artifacts/sticky")
    ap.add_argument("--triage-root", default="artifacts/triage")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    runs_root = (root / args.runs_root) if not Path(args.runs_root).is_absolute() else Path(args.runs_root)
    sticky_root = (root / args.sticky_root) if not Path(args.sticky_root).is_absolute() else Path(args.sticky_root)
    triage_root = (root / args.triage_root) if not Path(args.triage_root).is_absolute() else Path(args.triage_root)

    since = datetime.now() - timedelta(days=max(1, args.window_days))
    since_ts = since.timestamp()

    manifests = list_recent_files(runs_root, "run_*/manifest.json", since_ts)
    total_runs = 0
    failed_runs = 0
    failed_cmds = 0
    total_cmds = 0
    for p in manifests:
        m = load_json(p, {})
        total_runs += 1
        s = m.get("summary", {})
        if not s.get("ok", False):
            failed_runs += 1
        total_cmds += int(s.get("total", 0) or 0)
        failed_cmds += int(s.get("failed", 0) or 0)

    triages = list_recent_files(triage_root, "triage_*.json", since_ts)
    triage_fail_items = 0
    for p in triages:
        t = load_json(p, {})
        triage_fail_items += len(t.get("results", []))

    decisions = list_recent_files(sticky_root, "decision_*.json", since_ts)
    escalate_count = 0
    sticky_fix_count = 0
    infra_retry_count = 0
    for p in decisions:
        d = load_json(p, {})
        action = d.get("action", "")
        if action == "ESCALATE":
            escalate_count += 1
        elif action == "STICKY_FIX":
            sticky_fix_count += 1
        elif action == "INFRA_RETRY":
            infra_retry_count += 1

    decision_total = len(decisions)
    gate_fail_rate = (failed_runs / total_runs) if total_runs else 0.0
    cmd_fail_rate = (failed_cmds / total_cmds) if total_cmds else 0.0
    # proxy: not escalated among sticky/escalate decisions
    denom = escalate_count + sticky_fix_count
    fix_loop_convergence = (sticky_fix_count / denom) if denom else 1.0

    report = {
        "generated_at": datetime.now().isoformat(),
        "window_days": args.window_days,
        "since": since.isoformat(),
        "metrics": {
            "runs_total": total_runs,
            "runs_failed": failed_runs,
            "gate_fail_rate": round(gate_fail_rate, 4),
            "commands_total": total_cmds,
            "commands_failed": failed_cmds,
            "command_fail_rate": round(cmd_fail_rate, 4),
            "triage_files": len(triages),
            "triage_fail_items": triage_fail_items,
            "decisions_total": decision_total,
            "sticky_fix_count": sticky_fix_count,
            "escalate_count": escalate_count,
            "infra_retry_count": infra_retry_count,
            "fix_loop_convergence_proxy": round(fix_loop_convergence, 4),
        },
        "paths": {
            "runs_root": str(runs_root),
            "triage_root": str(triage_root),
            "sticky_root": str(sticky_root),
        },
    }

    out_json = Path(args.out_json) if args.out_json else root / "artifacts" / "ops" / f"pipeline_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if not out_json.is_absolute():
        out_json = root / out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out_md = Path(args.out_md) if args.out_md else out_json.with_suffix(".md")
    if not out_md.is_absolute():
        out_md = root / out_md
    md = [
        f"# Pipeline Health Report (last {args.window_days} days)",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Since: {report['since']}",
        "",
        "## Metrics",
        f"- Runs: {total_runs} (failed: {failed_runs}, gate_fail_rate: {report['metrics']['gate_fail_rate']})",
        f"- Commands: {total_cmds} (failed: {failed_cmds}, command_fail_rate: {report['metrics']['command_fail_rate']})",
        f"- Triage: files={len(triages)}, failed_items={triage_fail_items}",
        f"- Sticky decisions: total={decision_total}, sticky_fix={sticky_fix_count}, escalate={escalate_count}, infra_retry={infra_retry_count}",
        f"- Fix-loop convergence (proxy): {report['metrics']['fix_loop_convergence_proxy']}",
        "",
        "## Notes",
        "- fix_loop_convergence_proxy = sticky_fix / (sticky_fix + escalate)",
        "- This is a trend proxy for scheduled巡检; not a formal quality gate.",
    ]
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"out_json": str(out_json), "out_md": str(out_md), "metrics": report["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

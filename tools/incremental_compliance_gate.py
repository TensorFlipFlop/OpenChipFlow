#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def _git_status(workspace: Path) -> list[tuple[str, str]]:
    probe = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "git status failed")

    items: list[tuple[str, str]] = []
    for raw in probe.stdout.splitlines():
        if not raw:
            continue
        status = raw[:2]
        path_part = raw[3:]
        if "->" in path_part:
            old_path, new_path = [part.strip() for part in path_part.split("->", 1)]
            items.append((f"{status} rename_from", old_path))
            items.append((f"{status} rename_to", new_path))
            continue
        items.append((status, path_part.strip()))
    return items


def _matches_scope(path: str, scope_roots: list[str]) -> bool:
    p = Path(path)
    for root in scope_roots:
        if root == ".":
            return True
        root_path = Path(root)
        if p == root_path or root_path in p.parents:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce incremental patch scope against handoff context")
    ap.add_argument("--context", required=True, help="handoff_context.json path")
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--out", default="", help="optional report output path")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    context_path = Path(args.context)
    if not context_path.is_absolute():
        context_path = (workspace / context_path).resolve()
    if not context_path.exists():
        print(f"[COMPLIANCE][FAIL] missing context: {context_path}")
        return 2

    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[COMPLIANCE][FAIL] failed to parse context {context_path}: {exc}")
        return 2

    scope = context.get("design_scope", {})
    change_scope = context.get("change_scope", {})
    scope_roots = scope.get("scope_roots", [])
    allowed_modify = set(change_scope.get("allowed_modify", []))
    allowed_create = set(change_scope.get("allowed_create", []))
    forbidden_actions = change_scope.get("forbidden_actions", [])

    report = {
        "context": str(context_path),
        "workspace": str(workspace),
        "scope_roots": scope_roots,
        "allowed_modify": sorted(allowed_modify),
        "allowed_create": sorted(allowed_create),
        "forbidden_actions": forbidden_actions,
        "evaluated_changes": [],
        "violations": [],
    }

    try:
        changed_items = _git_status(workspace)
    except Exception as exc:
        print(f"[COMPLIANCE][FAIL] {exc}")
        return 2

    for status, rel_path in changed_items:
        if not rel_path or not _matches_scope(rel_path, scope_roots):
            continue

        normalized = rel_path.strip()
        kind = "modified"
        code = status.strip() or "??"
        if "rename_" in status:
            kind = "rename"
            report["violations"].append(
                {
                    "path": normalized,
                    "status": status,
                    "reason": "rename operations are not permitted in P0 incremental flow",
                }
            )
        elif code in {"??", "A"}:
            kind = "created"
            if normalized not in allowed_create:
                report["violations"].append(
                    {
                        "path": normalized,
                        "status": status,
                        "reason": "new file is outside allowed_create scope",
                    }
                )
        elif "D" in code:
            kind = "deleted"
            report["violations"].append(
                {
                    "path": normalized,
                    "status": status,
                    "reason": "deletions are not permitted in P0 incremental flow",
                }
            )
        else:
            if normalized not in allowed_modify and normalized not in allowed_create:
                report["violations"].append(
                    {
                        "path": normalized,
                        "status": status,
                        "reason": "modified file is outside allowed_modify scope",
                    }
                )
        report["evaluated_changes"].append(
            {
                "path": normalized,
                "status": status,
                "kind": kind,
            }
        )

    passed = not report["violations"]
    report["passed"] = passed

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = (workspace / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if passed:
        print("[COMPLIANCE][OK] incremental scope satisfied")
        return 0

    print("[COMPLIANCE][FAIL] incremental scope violated")
    for item in report["violations"]:
        print(f"- {item['path']}: {item['reason']} ({item['status']})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

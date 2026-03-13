#!/usr/bin/env python3
"""Pre-task quota guard.

- Enforces Codex quota threshold (5h + Week)
- Ensures quota snapshot freshness (auto-refresh once when stale)
- Optionally evaluates Gemini quota when text is provided

Exit codes:
- 0: pass
- 2: blocked by threshold
- 1: unable to evaluate required quota
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run_json(cmd: list[str]) -> tuple[int, dict | None, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    raw = (p.stdout or "").strip() or (p.stderr or "").strip()
    try:
        obj = json.loads(raw) if raw else None
    except Exception:
        obj = None
    return p.returncode, obj, raw


def run_codex_quota_check(codex_script: str, min_left: float, max_age_sec: float) -> tuple[int, dict | None, str]:
    return run_json(
        [
            codex_script,
            "--json",
            "--min-left",
            str(min_left),
            "--max-age-sec",
            str(max_age_sec),
            "--enforce",
        ]
    )


def refresh_codex_quota(project_root: Path, timeout_sec: float) -> bool:
    """Trigger one lightweight Codex call so local session logs get fresh rate_limits."""
    cmd = [
        "codex",
        "exec",
        "-C",
        str(project_root),
        "Reply with exactly OK.",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except FileNotFoundError:
        print("[ERR] codex binary not found while refreshing quota")
        return False
    except subprocess.TimeoutExpired:
        print(f"[ERR] codex refresh timed out after {timeout_sec:.1f}s")
        return False

    if p.returncode != 0:
        print(f"[ERR] codex refresh failed rc={p.returncode}")
        if p.stdout:
            print(p.stdout.strip())
        if p.stderr:
            print(p.stderr.strip())
        return False
    return True


def print_codex_state(tag: str, obj: dict | None) -> None:
    if obj is None:
        return
    status = "PASS" if obj.get("ok") else "BLOCK"
    age = obj.get("snapshot_age_sec")
    max_age = obj.get("max_age_sec")
    freshness = "fresh" if obj.get("fresh") else "stale"
    extra = ""
    if age is not None and max_age is not None:
        extra = f" age={age}s/{max_age}s {freshness}"
    print(f"[Codex] {tag} {status}{extra} {obj.get('buckets')}")


def stale_snapshot_is_safe_to_allow(
    obj: dict | None,
    *,
    max_snapshot_age_sec: float,
    min_left_percent: float,
) -> bool:
    if not isinstance(obj, dict):
        return False
    if not obj.get("ok_quota"):
        return False

    try:
        age = float(obj.get("snapshot_age_sec", 0.0))
    except Exception:
        return False
    if age > max_snapshot_age_sec:
        return False

    buckets = obj.get("buckets") or {}
    primary = buckets.get("primary") or {}
    secondary = buckets.get("secondary") or {}
    safe_left = max(float(min_left_percent), 25.0)
    try:
        primary_left = float(primary.get("left_percent", 0.0))
        secondary_left = float(secondary.get("left_percent", 0.0))
    except Exception:
        return False
    return primary_left >= safe_left and secondary_left >= safe_left


def main() -> int:
    ap = argparse.ArgumentParser(description="quota guard before running tasks")
    ap.add_argument("--min-left", type=float, default=5.0)
    ap.add_argument("--max-age-sec", type=float, default=600.0, help="max accepted quota snapshot age")
    ap.add_argument("--refresh-timeout-sec", type=float, default=90.0)
    ap.add_argument(
        "--stale-allow-age-sec",
        type=float,
        default=3600.0,
        help="allow stale snapshot when quota headroom is high and age is within this limit",
    )
    ap.add_argument("--gemini-status-text", default=None, help="optional Gemini /status text")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    project_root = root.parent
    codex_script = str(root / "codex_quota_status.py")
    gemini_script = str(root / "gemini_quota_status.py")

    rc, obj, raw = run_codex_quota_check(codex_script, args.min_left, args.max_age_sec)
    if obj is None:
        print("[ERR] codex quota parse failed")
        print(raw)
        return 1

    print_codex_state("CHECK", obj)

    if rc == 3:
        print("[WARN] codex quota snapshot is stale, refreshing once...")
        if not refresh_codex_quota(project_root=project_root, timeout_sec=args.refresh_timeout_sec):
            if stale_snapshot_is_safe_to_allow(
                obj,
                max_snapshot_age_sec=args.stale_allow_age_sec,
                min_left_percent=args.min_left,
            ):
                print(
                    "[WARN] unable to refresh codex quota snapshot; "
                    "allowing run because the last snapshot is recent enough and quota headroom is high"
                )
                print(
                    f"[HINT] stale grace: age<={args.stale_allow_age_sec:.0f}s and both quota buckets >=25%"
                )
                rc = 0
            else:
                print("[ERR] unable to refresh codex quota snapshot")
                return 1

        if rc == 3:
            rc, obj, raw = run_codex_quota_check(codex_script, args.min_left, args.max_age_sec)
            if obj is None:
                print("[ERR] codex quota parse failed after refresh")
                print(raw)
                return 1
            print_codex_state("RECHECK", obj)

    # strict policy by default: still stale after refresh => block for safety
    if rc == 3:
        if stale_snapshot_is_safe_to_allow(
            obj,
            max_snapshot_age_sec=args.stale_allow_age_sec,
            min_left_percent=args.min_left,
        ):
            print(
                "[WARN] codex quota snapshot remains stale after refresh; "
                "allowing run because the last snapshot is recent enough and quota headroom is high"
            )
            print(
                f"[HINT] stale grace: age<={args.stale_allow_age_sec:.0f}s and both quota buckets >=25%"
            )
            rc = 0
        else:
            print("[ERR] codex quota snapshot remains stale after refresh; task refused")
            return 1

    if rc == 3:
        print("[ERR] codex quota snapshot remains stale after refresh; task refused")
        return 1

    if rc == 2:
        return 2
    if rc != 0:
        return 1

    if args.gemini_status_text:
        rc2, obj2, raw2 = run_json([
            gemini_script,
            "--json",
            "--min-left",
            str(args.min_left),
            "--enforce",
            "--text",
            args.gemini_status_text,
        ])
        if obj2 is None:
            print("[WARN] gemini quota parse failed")
            print(raw2)
            return 1
        print("[Gemini]", "PASS" if obj2.get("ok") else "BLOCK", obj2.get("buckets"))
        if rc2 == 2:
            return 2

    print("[OK] quota guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

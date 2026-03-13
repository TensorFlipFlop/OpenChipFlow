#!/usr/bin/env python3
"""Read Codex quota usage from local ~/.codex session jsonl logs.

Outputs current 5h/Week quota usage and supports threshold enforcement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from dataclasses import dataclass
from typing import Any, Optional


WINDOW_LABELS = {
    300: "5h",
    10080: "Week",
}


@dataclass
class Bucket:
    label: str
    used_percent: float
    left_percent: float
    window_minutes: int
    resets_at: Optional[int]

    def to_dict(self) -> dict[str, Any]:
        out = {
            "label": self.label,
            "used_percent": self.used_percent,
            "left_percent": self.left_percent,
            "window_minutes": self.window_minutes,
            "resets_at": self.resets_at,
            "resets_at_local": None,
        }
        if self.resets_at:
            out["resets_at_local"] = dt.datetime.fromtimestamp(
                self.resets_at, dt.timezone(dt.timedelta(hours=8))
            ).isoformat()
        return out


@dataclass
class Snapshot:
    session_file: str
    event_ts_epoch: float
    event_ts_raw: Optional[str]
    rate_limits: dict[str, Any]


def parse_iso_ts_to_epoch(raw_ts: Optional[str]) -> Optional[float]:
    if not raw_ts or not isinstance(raw_ts, str):
        return None
    txt = raw_ts.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(txt).timestamp()
    except Exception:
        return None


def list_session_files(sessions_root: str, scan_limit: int) -> list[str]:
    pattern = os.path.join(os.path.expanduser(sessions_root), "**", "*.jsonl")
    files = glob.glob(pattern, recursive=True)
    if not files:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if scan_limit > 0:
        return files[:scan_limit]
    return files


def extract_latest_rate_limits_from_file(path: str) -> Optional[Snapshot]:
    latest: Optional[Snapshot] = None
    file_mtime = os.path.getmtime(path)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "event_msg":
                continue
            payload = obj.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            rl = payload.get("rate_limits")
            if not isinstance(rl, dict):
                continue

            raw_ts = obj.get("timestamp")
            event_ts_epoch = parse_iso_ts_to_epoch(raw_ts)
            if event_ts_epoch is None:
                event_ts_epoch = file_mtime

            latest = Snapshot(
                session_file=path,
                event_ts_epoch=event_ts_epoch,
                event_ts_raw=raw_ts,
                rate_limits=rl,
            )

    return latest


def find_latest_rate_limits(sessions_root: str, scan_limit: int) -> tuple[Optional[Snapshot], int]:
    files = list_session_files(sessions_root, scan_limit)
    best: Optional[Snapshot] = None

    for p in files:
        snap = extract_latest_rate_limits_from_file(p)
        if snap is None:
            continue
        if best is None or snap.event_ts_epoch > best.event_ts_epoch:
            best = snap

    return best, len(files)


def make_bucket(name: str, raw: dict[str, Any]) -> Bucket:
    used = float(raw.get("used_percent", 0.0))
    mins = int(raw.get("window_minutes", 0))
    label = WINDOW_LABELS.get(mins, name)
    left = max(0.0, 100.0 - used)
    resets_at = raw.get("resets_at")
    if resets_at is not None:
        try:
            resets_at = int(resets_at)
        except Exception:
            resets_at = None
    return Bucket(label=label, used_percent=used, left_percent=left, window_minutes=mins, resets_at=resets_at)


def format_bucket_text(b: Bucket) -> str:
    reset = "unknown"
    if b.resets_at:
        reset = dt.datetime.fromtimestamp(
            b.resets_at, dt.timezone(dt.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"{b.label}: left={b.left_percent:.1f}% used={b.used_percent:.1f}% reset={reset}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Codex quota status from local session logs")
    ap.add_argument("--sessions-root", default="~/.codex/sessions", help="codex session root directory")
    ap.add_argument("--scan-limit", type=int, default=200, help="max recent files to scan (0 means all)")
    ap.add_argument("--min-left", type=float, default=5.0, help="minimum left%% threshold (default: 5)")
    ap.add_argument("--max-age-sec", type=float, default=600.0, help="maximum accepted snapshot age in seconds")
    ap.add_argument("--enforce", action="store_true", help="exit non-zero when below threshold or stale")
    ap.add_argument("--json", action="store_true", help="json output")
    args = ap.parse_args()

    snap, scanned_files = find_latest_rate_limits(args.sessions_root, args.scan_limit)
    if not snap:
        msg = f"No usable rate_limits found under {os.path.expanduser(args.sessions_root)}"
        if args.json:
            print(json.dumps({"ok": False, "error": msg, "scanned_files": scanned_files}, ensure_ascii=False))
        else:
            print(f"[ERR] {msg}")
        return 1

    rl = snap.rate_limits
    primary = make_bucket("primary", rl.get("primary") or {})
    secondary = make_bucket("secondary", rl.get("secondary") or {})

    low_labels = []
    for b in (primary, secondary):
        if b.left_percent < args.min_left:
            low_labels.append(b.label)

    now_epoch = dt.datetime.now(dt.timezone.utc).timestamp()
    age_seconds = max(0.0, now_epoch - snap.event_ts_epoch)
    fresh = age_seconds <= max(0.0, float(args.max_age_sec))

    ok_quota = len(low_labels) == 0
    ok = ok_quota and fresh

    if args.json:
        out = {
            "ok": ok,
            "ok_quota": ok_quota,
            "fresh": fresh,
            "snapshot_age_sec": round(age_seconds, 3),
            "max_age_sec": args.max_age_sec,
            "threshold_left_percent": args.min_left,
            "session_file": snap.session_file,
            "snapshot_timestamp": snap.event_ts_raw,
            "scanned_files": scanned_files,
            "limit_id": rl.get("limit_id"),
            "buckets": {
                "primary": primary.to_dict(),
                "secondary": secondary.to_dict(),
            },
            "low_buckets": low_labels,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"session_file: {snap.session_file}")
        if snap.event_ts_raw:
            print(f"snapshot_timestamp: {snap.event_ts_raw}")
        print(f"snapshot_age_sec: {age_seconds:.1f} (max {args.max_age_sec:.1f})")
        print(format_bucket_text(primary))
        print(format_bucket_text(secondary))
        if not fresh:
            print(f"[STALE] quota snapshot is too old (> {args.max_age_sec:.1f}s)")
        if ok_quota:
            print(f"[OK] quota left is above threshold {args.min_left:.1f}%")
        else:
            print(f"[ALERT] low quota buckets: {', '.join(low_labels)} (< {args.min_left:.1f}%)")

    if args.enforce:
        if not fresh:
            return 3
        if not ok_quota:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Best-effort Gemini quota status extractor.

Methods (in order):
1) Parse explicit text via --text / stdin (recommended, stable)
2) Parse local cache file ~/.gemini/quota_status.json (optional)
3) (opt-in) Try `gemini -p "/status"` output parsing via --allow-cli-probe

Normalizes Day/Week label to Week (per local observed behavior).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Optional


RE_5H = re.compile(r"(?P<label>5h|6h|5小时|6小时)\s+(?P<left>[0-9]+(?:\.[0-9]+)?)%\s+left", re.IGNORECASE)
RE_WEEK_DAY = re.compile(r"(?P<label>Week|Day|周|天)\s+(?P<left>[0-9]+(?:\.[0-9]+)?)%\s+left", re.IGNORECASE)


def parse_from_text(text: str) -> Optional[dict]:
    m1 = RE_5H.search(text)
    m2 = RE_WEEK_DAY.search(text)
    if not m1 or not m2:
        return None

    left_5h = float(m1.group("left"))
    label2 = m2.group("label")
    left_week = float(m2.group("left"))

    # Normalize Day => Week (observed UI label inconsistency)
    if label2.lower() in {"day", "天"}:
        label2 = "Week"

    return {
        "primary": {"label": "5h", "left_percent": left_5h, "used_percent": max(0.0, 100.0 - left_5h)},
        "secondary": {"label": "Week", "left_percent": left_week, "used_percent": max(0.0, 100.0 - left_week)},
    }


def read_cache_file() -> Optional[str]:
    p = os.path.expanduser("~/.gemini/quota_status.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            txt = obj.get("raw_text")
            if isinstance(txt, str) and txt.strip():
                return txt
    except Exception:
        return None
    return None


def try_gemini_status_cmd(timeout_sec: int = 25) -> Optional[str]:
    cmd = ["gemini", "-p", "/status", "--output-format", "text"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except Exception:
        return None

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if not combined.strip():
        return None

    # If Gemini falls into auth/trust interactive flow, treat as unusable.
    lower = combined.lower()
    interactive_markers = [
        "waiting for auth",
        "do you trust this folder",
        "press esc",
        "logged in with google",
    ]
    if any(m in lower for m in interactive_markers):
        return None

    return combined


def main() -> int:
    ap = argparse.ArgumentParser(description="Gemini quota status (best effort)")
    ap.add_argument("--text", default=None, help="explicit status text to parse")
    ap.add_argument("--stdin", action="store_true", help="read status text from stdin (explicit opt-in)")
    ap.add_argument("--min-left", type=float, default=5.0, help="minimum left%% threshold (default: 5)")
    ap.add_argument("--enforce", action="store_true", help="exit non-zero when below threshold")
    ap.add_argument("--json", action="store_true", help="json output")
    ap.add_argument("--allow-cli-probe", action="store_true", help="allow probing `gemini -p /status` as fallback")
    args = ap.parse_args()

    raw = None
    source = None

    if args.text:
        raw = args.text
        source = "arg"
    elif args.stdin:
        data = sys.stdin.read()
        if data.strip():
            raw = data
            source = "stdin"

    if raw is None:
        c = read_cache_file()
        if c:
            raw = c
            source = "cache"

    if raw is None and args.allow_cli_probe:
        c = try_gemini_status_cmd()
        if c:
            raw = c
            source = "gemini_cmd"

    parsed = parse_from_text(raw or "") if raw else None

    if not parsed:
        msg = "Unable to parse Gemini 5h/Week quota from available sources"
        out = {"ok": False, "error": msg, "source": source}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"[WARN] {msg}")
            if source:
                print(f"source: {source}")
        return 1

    p = parsed["primary"]
    s = parsed["secondary"]
    low = []
    if p["left_percent"] < args.min_left:
        low.append("5h")
    if s["left_percent"] < args.min_left:
        low.append("Week")

    ok = len(low) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "source": source,
                    "threshold_left_percent": args.min_left,
                    "buckets": parsed,
                    "low_buckets": low,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"source: {source}")
        print(f"5h: left={p['left_percent']:.1f}% used={p['used_percent']:.1f}%")
        print(f"Week: left={s['left_percent']:.1f}% used={s['used_percent']:.1f}%")
        if ok:
            print(f"[OK] quota left is above threshold {args.min_left:.1f}%")
        else:
            print(f"[ALERT] low quota buckets: {', '.join(low)} (< {args.min_left:.1f}%)")

    if args.enforce and not ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

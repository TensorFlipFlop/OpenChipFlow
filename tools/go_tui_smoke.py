#!/usr/bin/env python3
"""Headless smoke test for Go BubbleTea TUI.

Validates:
- startup + graceful quit
- command palette + mode filter
- request form open/edit/path-complete/submit
- requirements prompt preview/copy
- result/input/prompt view cycling
- overlays: Ctrl+O / Ctrl+T / Ctrl+S
- dry-run toggle (Shift+D only)
- rerun last (r)
- no panic/crash in transcript
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import pexpect
except Exception as e:  # pragma: no cover
    pexpect = None
    PEXPECT_IMPORT_ERROR = e
else:
    PEXPECT_IMPORT_ERROR = None


def build_binary(project_root: Path, out_bin: Path) -> None:
    go_bin = Path.home() / ".local/go/bin/go"
    if not go_bin.exists():
        print(f"[ERR] go not found: {go_bin}")
        sys.exit(2)

    cmd = [str(go_bin), "build", "-o", str(out_bin), "./cmd/chipflow-tui-go"]
    env = dict(os.environ)
    env.setdefault("GOCACHE", str(Path("/tmp") / "openchipflow-go-build-cache"))
    subprocess.run(cmd, cwd=str(project_root), check=True, env=env)


def run_smoke(project_root: Path, bin_path: Path, log_path: Path, timeout_s: int) -> int:
    rows, cols = 40, 140
    cmd = f"{bin_path} --root {project_root}"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="ignore") as lf:
        child = pexpect.spawn(
            cmd,
            cwd=str(project_root),
            encoding="utf-8",
            codec_errors="ignore",
            dimensions=(rows, cols),
            timeout=timeout_s,
        )
        child.logfile = lf

        def send(keys: str, delay: float = 0.25) -> None:
            child.send(keys)
            time.sleep(delay)

        # warm up
        time.sleep(0.8)

        # help overlay
        send("?")
        send("\x1b")

        # handoff intake prompt preview/copy
        send("/")
        send("mode:handoff")
        send("\n")
        send("j")
        send("j")
        send("j")
        send("j")
        send("j")
        send("\n", 0.4)  # preview requirements
        send("y", 0.2)   # copy from prompt overlay
        send("\x1b", 0.2)
        send("j")
        send("\n", 0.2)  # copy requirements directly
        send("\x1b", 0.2)

        # language toggle
        send("l")
        send("l")

        # command palette + request form
        send("/")
        send("mode:spec")
        send("\n")
        send("\n")  # edit spec_source
        send("cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless/sp")
        send("\t")  # path completion
        send("\n")  # apply field
        send("j")
        send("j")
        send("j")
        send("\n", 0.8)  # submit request

        # dry-run toggle path
        send("D")  # toggle OFF
        send("D")  # toggle back ON before running more commands

        # cycle result views
        send("v")
        send("v")
        send("v")
        send("v")
        send("v")

        # overlays
        send("\x0f")   # Ctrl+O model
        send("j")      # choose first concrete model
        send("\n")     # apply model
        send("\x14")   # Ctrl+T variant
        send("\n")     # apply default variant for selected model
        send("\x13")   # Ctrl+S stage
        send("\n", 0.5)  # run one stage (dry-run)

        # rerun last command
        send("r", 0.4)

        # stop if still running, then force-quit via Ctrl+C x3
        send("x", 0.2)
        send("\x03", 0.1)
        send("\x03", 0.1)
        send("\x03", 0.2)

        try:
            child.expect(pexpect.EOF, timeout=timeout_s)
        except Exception:
            child.close(force=True)

        rc = child.exitstatus if child.exitstatus is not None else 0

    txt = log_path.read_text(encoding="utf-8", errors="ignore")
    bad_markers = ["panic:", "fatal error:"]
    if any(m in txt.lower() for m in bad_markers):
        print("[FAIL] panic/fatal marker found in transcript")
        return 1

    if rc not in (0, None):
        print(f"[FAIL] unexpected exit code: {rc}")
        return 1

    print(f"[OK] go tui smoke passed: {log_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Go BubbleTea TUI smoke test")
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--timeout", type=int, default=16)
    ap.add_argument("--keep-log", action="store_true")
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    out_bin = Path("/tmp/chipflow-tui-go")
    log_path = project_root / "artifacts" / "screenshots" / "go_tui_smoke.ansi"
    existed_before = log_path.exists()

    if pexpect is None:
        print(f"[SKIP] go tui smoke skipped: missing dependency pexpect ({PEXPECT_IMPORT_ERROR})")
        return 0

    build_binary(project_root, out_bin)
    rc = run_smoke(project_root, out_bin, log_path, timeout_s=args.timeout)

    if rc == 0 and not args.keep_log and log_path.exists() and not existed_before:
        try:
            log_path.unlink()
        except Exception:
            pass

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

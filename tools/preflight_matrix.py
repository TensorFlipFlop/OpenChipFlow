#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from gitee_auth import check_gitee_auth as check_gitee_auth_unified

try:
    import yaml
except Exception:  # pragma: no cover
    print("[ERR] PyYAML is required. Install with: python3 -m pip install pyyaml")
    raise


def expand(path: str) -> str:
    return str(Path(path).expanduser())


def check_command(cmd: str) -> bool:
    p = shutil.which(cmd)
    if p:
        print(f"[OK] command {cmd}: {p}")
        return True
    print(f"[FAIL] command {cmd}: not found")
    return False


def check_python_module(name: str) -> bool:
    ok = importlib.util.find_spec(name) is not None
    if ok:
        print(f"[OK] python module {name}: installed")
    else:
        print(f"[FAIL] python module {name}: missing")
    return ok


def run_shell_check(command: str, name: str) -> bool:
    r = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode == 0:
        print(f"[OK] check {name}: {command}")
        return True
    print(f"[FAIL] check {name}: {command} (rc={r.returncode})")
    tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or []
    if tail:
        print(f"       {tail[0]}")
    return False


def check_gitee_auth(name: str = "gitee_auth_status") -> bool:
    auth = check_gitee_auth_unified(
        cli_timeout_sec=8,
        api_timeout_sec=5,
        user_agent="openchipflow-preflight/1.0",
    )
    if auth.get("ok", False) and auth.get("method") == "gitee auth status":
        print(f"[OK] check {name}: gitee auth status")
        return True

    if auth.get("ok", False):
        api_detail = auth.get("api_detail") or auth.get("detail", "api /user 200")
        print(f"[OK] check {name}: {api_detail} (fallback from gitee auth status)")
        return True

    print(f"[FAIL] check {name}: gitee auth status (rc={auth.get('status_rc')})")
    status_tail = auth.get("status_tail", "")
    if status_tail:
        print(f"       {status_tail}")
    api_detail = auth.get("api_detail", "")
    if api_detail:
        print(f"       fallback: {api_detail}")
    print("       [FIX] 完成 Gitee CLI 授权后重试：先执行 `gitee auth --help`，按文档配置授权码/令牌（~/.gitee/config.yml）。")
    return False


def check_path_exists(path: str, name: str) -> bool:
    p = expand(path)
    ok = Path(p).exists()
    if ok:
        print(f"[OK] check {name}: {p}")
    else:
        print(f"[FAIL] check {name}: {p} missing")
    return ok


def check_any_path_exists(paths: list[str], name: str) -> bool:
    resolved = [expand(x) for x in paths]
    for p in resolved:
        if Path(p).exists():
            print(f"[OK] check {name}: found {p}")
            return True
    print(f"[FAIL] check {name}: none exists -> {', '.join(resolved)}")
    return False


def uniq(seq):
    seen = set()
    out = []
    for x in seq:
        key = x
        if isinstance(x, dict):
            key = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def resolve_workflow(cfg: dict, wf: str, _stack: set[str] | None = None) -> dict:
    _stack = _stack or set()
    if wf in _stack:
        raise ValueError(f"workflow include cycle detected at {wf}")
    _stack.add(wf)

    common = cfg.get("common", {})
    workflows = cfg.get("workflows", {})
    if wf not in workflows:
        raise KeyError(f"workflow not found: {wf}")

    out = {
        "commands": list(common.get("commands", [])),
        "python_modules": list(common.get("python_modules", [])),
        "checks": list(common.get("checks", [])),
    }

    cur = workflows[wf]
    for inc in cur.get("include", []):
        sub = resolve_workflow(cfg, inc, _stack)
        out["commands"].extend(sub.get("commands", []))
        out["python_modules"].extend(sub.get("python_modules", []))
        out["checks"].extend(sub.get("checks", []))

    out["commands"].extend(cur.get("commands", []))
    out["python_modules"].extend(cur.get("python_modules", []))
    out["checks"].extend(cur.get("checks", []))

    out["commands"] = uniq(out["commands"])
    out["python_modules"] = uniq(out["python_modules"])
    out["checks"] = uniq(out["checks"])
    _stack.remove(wf)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenChipFlow preflight checker")
    ap.add_argument("--workflow", default="all", help="workflow name in config/preflight_rules.yaml")
    ap.add_argument("--config", default="config/preflight_rules.yaml", help="rules file")
    ap.add_argument("--strict-optional", action="store_true", help="treat optional commands as required")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = Path(__file__).resolve().parents[1] / cfg_path
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    rules = resolve_workflow(cfg, args.workflow)

    print(f"=== OpenChipFlow Preflight ({args.workflow}) ===")
    failed = False

    for c in rules.get("commands", []):
        failed = (not check_command(c)) or failed

    for m in rules.get("python_modules", []):
        failed = (not check_python_module(m)) or failed

    for chk in rules.get("checks", []):
        t = chk.get("type")
        name = chk.get("name", t or "check")
        ok = True
        if t == "command_help":
            ok = run_shell_check(chk["command"], name)
        elif t == "path_exists":
            ok = check_path_exists(chk["path"], name)
        elif t == "any_path_exists":
            ok = check_any_path_exists(chk.get("paths", []), name)
        elif t == "gitee_auth":
            ok = check_gitee_auth(name)
        else:
            print(f"[WARN] unknown check type: {t} ({name})")
        failed = (not ok) or failed

    print("\n--- Optional checks ---")
    for c in cfg.get("optional", {}).get("commands", []):
        ok = check_command(c)
        if args.strict_optional and not ok:
            failed = True

    if failed:
        print("\n[FAIL] preflight failed")
        return 2
    print("\n[OK] preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

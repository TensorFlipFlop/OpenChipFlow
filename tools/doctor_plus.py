#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from gitee_auth import check_gitee_auth

REQUIRED_COMMANDS = [
    "make",
    "git",
    "python3",
    "verilator",
    "verilator_coverage",
    "verible-verilog-format",
    "verible-verilog-lint",
    "verible-verilog-syntax",
    "lcov",
    "genhtml",
    "codex",
    "gemini",
    "opencode",
    "gitee",
]

OPTIONAL_COMMANDS = ["docker", "gtkwave", "vcs", "verdi", "claude"]
REQUIRED_MODULES = ["cocotb", "cocotb_bus", "cocotb_coverage", "pytest"]


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def cmd_ok(command: str) -> bool:
    r = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return r.returncode == 0


def gitee_auth_check() -> dict:
    auth = check_gitee_auth(
        cli_timeout_sec=8,
        api_timeout_sec=5,
        user_agent="openchipflow-doctor/1.0",
    )
    return {
        "ok": bool(auth.get("ok", False)),
        "rc": int(auth.get("status_rc", -1)),
        "method": auth.get("method", "none"),
        "hint": str(auth.get("detail", "")),
    }


def module_ok(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def collect() -> dict:
    data = {
        "generated_at": datetime.now().isoformat(),
        "cwd": str(Path.cwd()),
        "required_commands": {},
        "optional_commands": {},
        "required_modules": {},
        "checks": {},
        "summary": {},
    }

    for c in REQUIRED_COMMANDS:
        p = which(c)
        data["required_commands"][c] = {"ok": bool(p), "path": p}

    for c in OPTIONAL_COMMANDS:
        p = which(c)
        data["optional_commands"][c] = {"ok": bool(p), "path": p}

    for m in REQUIRED_MODULES:
        data["required_modules"][m] = {"ok": module_ok(m)}

    data["checks"]["gitee_pr_help"] = {"ok": cmd_ok("gitee pr --help")}
    data["checks"]["gitee_pr_create_help"] = {"ok": cmd_ok("gitee pr create --help")}
    data["checks"]["gitee_config"] = {"ok": Path.home().joinpath(".gitee/config.yml").exists()}
    data["checks"]["gitee_auth_status"] = gitee_auth_check()
    data["checks"]["codex_auth"] = {"ok": Path.home().joinpath(".codex/auth.json").exists()}

    req_cmd_ok = all(v["ok"] for v in data["required_commands"].values())
    req_mod_ok = all(v["ok"] for v in data["required_modules"].values())
    req_checks_ok = all(v["ok"] for v in data["checks"].values())

    data["summary"] = {
        "required_commands_ok": req_cmd_ok,
        "required_modules_ok": req_mod_ok,
        "required_checks_ok": req_checks_ok,
        "ok": req_cmd_ok and req_mod_ok and req_checks_ok,
    }
    return data


def print_human(data: dict) -> None:
    print("=== OpenChipFlow Doctor++ ===")
    print(f"generated_at: {data['generated_at']}")

    print("\n-- required commands --")
    for k, v in data["required_commands"].items():
        if v["ok"]:
            print(f"[OK] {k}: {v['path']}")
        else:
            print(f"[FAIL] {k}: not found")

    print("\n-- required python modules --")
    for k, v in data["required_modules"].items():
        print(f"[{'OK' if v['ok'] else 'FAIL'}] {k}")

    print("\n-- required checks --")
    for k, v in data["checks"].items():
        print(f"[{'OK' if v['ok'] else 'FAIL'}] {k}")

    print("\n-- optional commands --")
    for k, v in data["optional_commands"].items():
        print(f"[{'OK' if v['ok'] else 'WARN'}] {k}{': ' + v['path'] if v['ok'] else ''}")

    if not data["checks"].get("gitee_auth_status", {}).get("ok", False):
        hint = data["checks"].get("gitee_auth_status", {}).get("hint", "")
        print("\n[ADVICE] Gitee 授权未通过，自动化 PR 会失败。")
        print("         1) 执行 `gitee auth --help`，按文档配置授权码/令牌")
        print("         2) 确认 ~/.gitee/config.yml 已生成")
        print("         3) 复测: gitee auth status && gitee pr create --help")
        if hint:
            print(f"         hint: {hint}")

    print("\nsummary:", "PASS" if data["summary"]["ok"] else "FAIL")


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenChipFlow Doctor++")
    ap.add_argument("--json-out", default="", help="write JSON report to this path")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    data = collect()

    out = args.json_out
    if not out:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(root / "artifacts" / "doctor" / f"doctor_plus_{ts}.json")

    out_path = Path(out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print_human(data)
    print(f"\nreport: {out_path}")
    return 0 if data["summary"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

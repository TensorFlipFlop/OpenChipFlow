#!/usr/bin/env python3
"""Probe CLI capabilities for OpenChipFlow TUI/runtime mapping.

Outputs: artifacts/capabilities/capabilities.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


CODEx_REASONING_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
}

CODEx_REASONING_ORDER = ["low", "medium", "high", "xhigh"]

MODEL_FAMILY_ORDER = {
    "codex": 0,
    "gemini": 1,
    "opencode": 2,
    "other": 9,
}


def run_cmd(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 127, "", str(e)


def has_opt(text: str, *opts: str) -> bool:
    txt = text.lower()
    return all(o.lower() in txt for o in opts)


def parse_choices_block(text: str, flag: str) -> list[str]:
    # e.g. --approval-mode ... [choices: "default", "auto_edit", ...]
    pat = re.compile(rf"{re.escape(flag)}[^\n]*\[choices:\s*([^\]]+)\]", re.IGNORECASE)
    m = pat.search(text)
    if not m:
        return []
    raw = m.group(1)
    vals = [v.strip().strip('"\'') for v in raw.split(",")]
    return [v for v in vals if v]


def extract_flag_value(cmd: list[str], aliases: tuple[str, ...]) -> str | None:
    for i, tok in enumerate(cmd):
        if tok in aliases and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def load_codex_model_profiles() -> dict[str, dict[str, Any]]:
    cache_path = Path.home() / ".codex" / "models_cache.json"
    if not cache_path.exists():
        return {}

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    models = data.get("models")
    if not isinstance(models, list):
        return {}

    profiles: dict[str, dict[str, Any]] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue

        variants = [
            {"value": effort, "label": CODEx_REASONING_LABELS[effort]}
            for effort in CODEx_REASONING_ORDER
        ]

        default_variant = "high" if any(v["value"] == "high" for v in variants) else variants[0]["value"]
        profiles[slug] = {
            "family": "codex",
            "label": str(item.get("display_name") or slug),
            "default_variant": default_variant,
            "variants": variants,
            "source": str(cache_path),
        }

    return profiles


def load_gemini_model_profiles() -> dict[str, dict[str, Any]]:
    models = {"auto-gemini-3"}
    root = Path.home() / ".gemini" / "tmp"
    if root.exists():
        model_re = re.compile(r'"model"\s*:\s*"([^"]+)"')
        for path in root.rglob("session-*.json"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in model_re.finditer(text):
                model = match.group(1).strip()
                if model:
                    models.add(model)

    profiles: dict[str, dict[str, Any]] = {}
    for model in sorted(models):
        profiles[model] = {
            "family": "gemini",
            "label": model,
            "default_variant": None,
            "variants": [],
            "source": str(root),
        }
    return profiles


def load_opencode_model_profiles(
    runner_tool_map: dict[str, Any],
    native_variant_choices: list[str],
) -> dict[str, dict[str, Any]]:
    variants = native_variant_choices or ["low", "medium", "high"]
    variant_items = [{"value": v, "label": v.replace("_", " ").title()} for v in variants]
    profiles: dict[str, dict[str, Any]] = {}

    for tool in runner_tool_map.values():
        if tool.get("entry") != "opencode":
            continue
        model = tool.get("default_model")
        if not model:
            continue
        default_variant = tool.get("default_variant") or "high"
        profiles[model] = {
            "family": "opencode",
            "label": model,
            "default_variant": default_variant,
            "variants": variant_items,
            "source": "runner_tool_map",
        }
    return profiles


def sort_model_names(profiles: dict[str, dict[str, Any]]) -> list[str]:
    def sort_key(name: str) -> tuple[int, str]:
        family = str((profiles.get(name) or {}).get("family") or "other")
        return (MODEL_FAMILY_ORDER.get(family, MODEL_FAMILY_ORDER["other"]), name.lower())

    return sorted(profiles.keys(), key=sort_key)


def probe_one(name: str, bin_name: str, help_cmd: list[str]) -> dict[str, Any]:
    exe = shutil.which(bin_name)
    out: dict[str, Any] = {
        "name": name,
        "binary": bin_name,
        "found": bool(exe),
        "path": exe,
    }
    if not exe:
        return out

    rc, stdout, stderr = run_cmd(help_cmd)
    text = (stdout + "\n" + stderr).strip()
    out["help_rc"] = rc
    out["capabilities"] = {
        "model_switch": has_opt(text, "--model") or has_opt(text, "-m, --model"),
        "thinking_switch": has_opt(text, "--thinking"),
        "variant_switch": has_opt(text, "--variant"),
        "approval_mode": has_opt(text, "--approval-mode"),
    }
    out["choices"] = {
        "approval_mode": parse_choices_block(text, "--approval-mode"),
        "variant": parse_choices_block(text, "--variant"),
        "thinking": parse_choices_block(text, "--thinking"),
        "model": parse_choices_block(text, "--model"),
    }
    return out


def read_runner_tool_map(project_root: Path) -> dict[str, Any]:
    cfg = project_root / "cocotb_ex/ai_cli_pipeline/config.json"
    if not cfg.exists():
        return {}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return {}

    tools = data.get("ai_cli_tools", {})
    out = {}
    for k, v in tools.items():
        cmd = v.get("cmd") or []
        out[k] = {
            "runner": v.get("runner"),
            "cmd": cmd,
            "entry": cmd[0] if cmd else None,
            "uses_model": any(x in {"-m", "--model"} for x in cmd),
            "uses_variant": "--variant" in cmd,
            "uses_thinking": "--thinking" in cmd,
            "default_model": extract_flag_value(cmd, ("-m", "--model")),
            "default_variant": extract_flag_value(cmd, ("--variant",)),
            "default_thinking": extract_flag_value(cmd, ("--thinking",)),
        }
    return out


def build_runtime_catalog(runner_tool_map: dict[str, Any], tools_payload: dict[str, Any]) -> dict[str, Any]:
    models: set[str] = set()
    variants: set[str] = set()
    thinkings: set[str] = set()

    tool_defaults: dict[str, Any] = {}
    for name, tool in runner_tool_map.items():
        dm = tool.get("default_model")
        dv = tool.get("default_variant")
        dt = tool.get("default_thinking")
        if dm:
            models.add(dm)
        if dv:
            variants.add(dv)
        if dt:
            thinkings.add(dt)
        tool_defaults[name] = {
            "model": dm,
            "variant": dv,
            "thinking": dt,
        }

    model_profiles: dict[str, dict[str, Any]] = {}
    model_profiles.update(load_codex_model_profiles())
    model_profiles.update(load_gemini_model_profiles())
    opencode_variant_choices = (
        (((tools_payload.get("opencode") or {}).get("choices") or {}).get("variant")) or []
    )
    model_profiles.update(load_opencode_model_profiles(runner_tool_map, opencode_variant_choices))

    for name, profile in model_profiles.items():
        models.add(name)
        default_variant = profile.get("default_variant")
        if default_variant:
            variants.add(str(default_variant))
        for variant in profile.get("variants") or []:
            value = str((variant or {}).get("value") or "").strip()
            if value:
                variants.add(value)

    return {
        "models": sort_model_names(model_profiles) or sorted(models),
        "variants": sorted(variants),
        "thinking_levels": sorted(thinkings),
        "tool_defaults": tool_defaults,
        "model_profiles": model_profiles,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe codex/gemini/opencode capability matrix")
    ap.add_argument("--out", default="artifacts/capabilities/capabilities.json")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    out_path = (project_root / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    codex = probe_one("codex", "codex", ["codex", "exec", "--help"])
    gemini = probe_one("gemini", "gemini", ["gemini", "--help"])
    opencode = probe_one("opencode", "opencode", ["opencode", "run", "--help"])

    runner_tool_map = read_runner_tool_map(project_root)

    tools_payload = {
        "codex": codex,
        "gemini": gemini,
        "opencode": opencode,
    }

    payload = {
        "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
        "project_root": str(project_root),
        "tools": tools_payload,
        "runner_tool_map": runner_tool_map,
        "runtime_catalog": build_runtime_catalog(runner_tool_map, tools_payload),
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

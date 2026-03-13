#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = "artifact_handoff_manifest/v1"


class HandoffError(ValueError):
    pass


def load_handoff_manifest(manifest_path: str | Path) -> tuple[dict[str, Any], Path]:
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not manifest_file.exists():
        raise HandoffError(f"handoff manifest missing: {manifest_file}")
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HandoffError(f"failed to parse handoff manifest {manifest_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise HandoffError(f"handoff manifest must be a JSON object: {manifest_file}")
    return data, manifest_file


def _require_string(section: dict[str, Any], key: str, label: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _require_string_list(
    section: dict[str, Any], key: str, label: str, *, allow_empty: bool = False
) -> list[str]:
    value = section.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        requirement = "an array" if allow_empty else "a non-empty array"
        raise HandoffError(f"{label}.{key} must be {requirement}")
    cleaned: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise HandoffError(f"{label}.{key}[{idx}] must be a non-empty string")
        cleaned.append(item.strip())
    return cleaned


def _require_path_item_list(
    section: dict[str, Any], key: str, label: str, *, allow_empty: bool = False
) -> list[str]:
    value = section.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        requirement = "an array" if allow_empty else "a non-empty array"
        raise HandoffError(f"{label}.{key} must be {requirement}")
    cleaned: list[str] = []
    for idx, item in enumerate(value):
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
            continue
        if isinstance(item, dict):
            raw_path = item.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                cleaned.append(raw_path.strip())
                continue
        raise HandoffError(
            f"{label}.{key}[{idx}] must be a non-empty string or object with non-empty path"
        )
    return cleaned


def _require_backend_list(section: dict[str, Any], key: str, label: str) -> list[str]:
    value = section.get(key)
    if not isinstance(value, list) or not value:
        raise HandoffError(f"{label}.{key} must be a non-empty array")
    cleaned: list[str] = []
    for idx, item in enumerate(value):
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip())
            continue
        if isinstance(item, dict):
            raw_name = item.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                cleaned.append(raw_name.strip())
                continue
        raise HandoffError(
            f"{label}.{key}[{idx}] must be a non-empty string or object with non-empty name"
        )
    return cleaned


def _resolve_workspace_path(workspace: Path, raw_path: str, label: str) -> dict[str, Any]:
    expanded = Path(raw_path).expanduser()
    resolved = expanded.resolve() if expanded.is_absolute() else (workspace / expanded).resolve()
    try:
        rel = str(resolved.relative_to(workspace))
    except ValueError as exc:
        raise HandoffError(f"{label} must resolve inside workspace {workspace}: {raw_path}") from exc
    return {
        "input": raw_path,
        "abs": str(resolved),
        "workspace_rel": rel,
        "exists": resolved.exists(),
    }


def _normalize_path_list(workspace: Path, paths: list[str], label: str) -> list[str]:
    out: list[str] = []
    for raw_path in paths:
        info = _resolve_workspace_path(workspace, raw_path, label)
        out.append(info["workspace_rel"])
    return sorted(dict.fromkeys(out))


def _scope_roots(paths: list[str]) -> list[str]:
    roots = set()
    for rel_path in paths:
        parent = str(Path(rel_path).parent)
        roots.add("." if parent in ("", ".") else parent)
    return sorted(roots)


def build_handoff_context(
    manifest: dict[str, Any],
    manifest_file: Path,
    workspace: str | Path,
    *,
    expected_delivery_state: str | None = None,
    context_output: str = "artifacts/handoff/handoff_context.json",
) -> dict[str, Any]:
    workspace_root = Path(workspace).expanduser().resolve()
    if not workspace_root.exists():
        raise HandoffError(f"workspace missing: {workspace_root}")

    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise HandoffError(
            f"schema_version must be {SUPPORTED_SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    case_id = _require_string(manifest, "case_id", "manifest")
    delivery_state = _require_string(manifest, "delivery_state", "manifest")
    if expected_delivery_state and delivery_state != expected_delivery_state:
        raise HandoffError(
            f"delivery_state must be {expected_delivery_state!r} for this flow, got {delivery_state!r}"
        )

    docs = manifest.get("docs")
    if not isinstance(docs, dict):
        raise HandoffError("manifest.docs must be an object")
    docs_info = {
        "spec_file": _resolve_workspace_path(
            workspace_root, _require_string(docs, "spec_file", "docs"), "docs.spec_file"
        ),
        "reqs_file": _resolve_workspace_path(
            workspace_root, _require_string(docs, "reqs_file", "docs"), "docs.reqs_file"
        ),
        "testplan_file": _resolve_workspace_path(
            workspace_root, _require_string(docs, "testplan_file", "docs"), "docs.testplan_file"
        ),
        "baseline_summary_file": _resolve_workspace_path(
            workspace_root,
            _require_string(docs, "baseline_summary_file", "docs"),
            "docs.baseline_summary_file",
        ),
        "compat_constraints_file": _resolve_workspace_path(
            workspace_root,
            _require_string(docs, "compat_constraints_file", "docs"),
            "docs.compat_constraints_file",
        ),
    }
    allowlist_doc = docs.get("allowlist_file")
    if isinstance(allowlist_doc, str) and allowlist_doc.strip():
        docs_info["allowlist_file"] = _resolve_workspace_path(
            workspace_root, allowlist_doc.strip(), "docs.allowlist_file"
        )
    else:
        docs_info["allowlist_file"] = {
            "input": "",
            "abs": "",
            "workspace_rel": "",
            "exists": False,
        }

    design_assets = manifest.get("design_assets")
    if not isinstance(design_assets, dict):
        raise HandoffError("manifest.design_assets must be an object")
    design_info = {
        "rtl_file": _resolve_workspace_path(
            workspace_root,
            _require_string(design_assets, "rtl_file", "design_assets"),
            "design_assets.rtl_file",
        ),
        "rtl_filelist": _resolve_workspace_path(
            workspace_root,
            _require_string(design_assets, "rtl_filelist", "design_assets"),
            "design_assets.rtl_filelist",
        ),
        "tb_wrapper_file": _resolve_workspace_path(
            workspace_root,
            _require_string(design_assets, "tb_wrapper_file", "design_assets"),
            "design_assets.tb_wrapper_file",
        ),
        "tb_py_file": _resolve_workspace_path(
            workspace_root,
            _require_string(design_assets, "tb_py_file", "design_assets"),
            "design_assets.tb_py_file",
        ),
        "test_file": _resolve_workspace_path(
            workspace_root,
            _require_string(design_assets, "test_file", "design_assets"),
            "design_assets.test_file",
        ),
        "top_level": _require_string(design_assets, "top_level", "design_assets"),
        "test_module": _require_string(design_assets, "test_module", "design_assets"),
        "smoke_testcase": (
            design_assets.get("smoke_testcase", "").strip()
            if isinstance(design_assets.get("smoke_testcase"), str)
            else ""
        ),
    }

    change_scope = manifest.get("change_scope")
    if not isinstance(change_scope, dict):
        raise HandoffError("manifest.change_scope must be an object")
    allowed_modify = _normalize_path_list(
        workspace_root,
        _require_path_item_list(change_scope, "allowed_modify", "change_scope"),
        "change_scope.allowed_modify",
    )
    allowed_create = _normalize_path_list(
        workspace_root,
        _require_path_item_list(change_scope, "allowed_create", "change_scope", allow_empty=True),
        "change_scope.allowed_create",
    )
    forbidden_actions = _require_string_list(
        change_scope, "forbidden_actions", "change_scope"
    )

    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        raise HandoffError("manifest.verification must be an object")
    backends = _require_backend_list(verification, "backends", "verification")
    regression_modules = verification.get("regression_modules", [])
    if regression_modules:
        if not isinstance(regression_modules, list) or not all(
            isinstance(item, str) and item.strip() for item in regression_modules
        ):
            raise HandoffError("verification.regression_modules must be an array of strings")
        regression_modules = [item.strip() for item in regression_modules]
    else:
        regression_modules = []
    smoke_testcase = ""
    if isinstance(verification.get("smoke_testcase"), str):
        smoke_testcase = verification["smoke_testcase"].strip()
    if not smoke_testcase:
        smoke_testcase = design_info["smoke_testcase"] or "run_basic"

    missing_required = []
    for group in (docs_info, design_info):
        for key, value in group.items():
            if not isinstance(value, dict):
                continue
            if not value["exists"]:
                missing_required.append(f"{key}:{value['workspace_rel'] or value['input']}")
    if missing_required:
        raise HandoffError("missing required handoff files: " + ", ".join(missing_required))

    tracked_files = sorted(
        dict.fromkeys(
            allowed_modify
            + allowed_create
            + [
                design_info["rtl_file"]["workspace_rel"],
                design_info["rtl_filelist"]["workspace_rel"],
                design_info["tb_wrapper_file"]["workspace_rel"],
                design_info["tb_py_file"]["workspace_rel"],
                design_info["test_file"]["workspace_rel"],
            ]
        )
    )
    design_scope_roots = _scope_roots(tracked_files)
    output_info = _resolve_workspace_path(workspace_root, context_output, "context_output")
    sim_dir = workspace_root / "sim"
    sim_rtl_filelist_path = os.path.relpath(design_info["rtl_filelist"]["abs"], sim_dir)

    try:
        manifest_rel = str(manifest_file.resolve().relative_to(workspace_root))
    except ValueError:
        manifest_rel = str(manifest_file.resolve())

    derived_global_params = {
        "inbox_spec_path": docs_info["spec_file"]["workspace_rel"],
        "spec_path": docs_info["spec_file"]["workspace_rel"],
        "reqs_path": docs_info["reqs_file"]["workspace_rel"],
        "testplan_path": docs_info["testplan_file"]["workspace_rel"],
        "baseline_summary_path": docs_info["baseline_summary_file"]["workspace_rel"],
        "compat_constraints_path": docs_info["compat_constraints_file"]["workspace_rel"],
        "allowlist_doc_path": docs_info["allowlist_file"]["workspace_rel"],
        "rtl_path": design_info["rtl_file"]["workspace_rel"],
        "rtl_filelist_path": design_info["rtl_filelist"]["workspace_rel"],
        "sim_rtl_filelist_path": sim_rtl_filelist_path,
        "tb_wrapper_path": design_info["tb_wrapper_file"]["workspace_rel"],
        "tb_py_path": design_info["tb_py_file"]["workspace_rel"],
        "test_path": design_info["test_file"]["workspace_rel"],
        "toplevel_name": design_info["top_level"],
        "test_module_name": design_info["test_module"],
        "smoke_testcase_name": smoke_testcase,
        "handoff_manifest_path": manifest_rel,
        "handoff_context_path": output_info["workspace_rel"],
    }
    if regression_modules:
        derived_global_params["regression_modules"] = " ".join(regression_modules)

    return {
        "schema_version": "handoff_context/v1",
        "manifest": {
            "path": manifest_rel,
            "abs": str(manifest_file.resolve()),
        },
        "workspace": str(workspace_root),
        "case_id": case_id,
        "delivery_state": delivery_state,
        "docs": docs_info,
        "design_assets": design_info,
        "change_scope": {
            "allowed_modify": allowed_modify,
            "allowed_create": allowed_create,
            "forbidden_actions": forbidden_actions,
        },
        "verification": {
            "backends": backends,
            "smoke_testcase": smoke_testcase,
            "regression_modules": regression_modules,
        },
        "design_scope": {
            "tracked_files": tracked_files,
            "scope_roots": design_scope_roots,
        },
        "output": output_info,
        "derived_global_params": derived_global_params,
    }

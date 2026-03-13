#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def _ensure_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside {root}: {resolved}") from exc
    return resolved


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "src_abs": str(src.resolve()),
        "dst_abs": str(dst.resolve()),
        "size": dst.stat().st_size,
        "sha256": _sha256(dst),
    }


def _session_workspace_paths(workspace_root: Path, session_root: Path) -> dict[str, Path]:
    session_root = _ensure_within(session_root, workspace_root, "session_root")
    return {
        "session_root": session_root,
        "session_root_rel": Path(_safe_rel(session_root, workspace_root)),
        "imports_dir": session_root / "inputs",
        "workspace_dir": session_root / "workspace",
        "handoff_dir": session_root / "handoff",
        "docs_dir": session_root / "workspace" / "handoff",
        "spec_out_dir": session_root / "workspace" / "ai_cli_pipeline" / "specs" / "out",
    }


def infer_session_root_from_path(path: Path, workspace_root: Path) -> Path | None:
    resolved = path.resolve()
    workspace_root = workspace_root.resolve()
    try:
        rel = resolved.relative_to(workspace_root)
    except ValueError:
        return None
    parts = rel.parts
    for idx in range(len(parts) - 2):
        if parts[idx : idx + 2] == ("artifacts", "sessions"):
            return workspace_root / Path(*parts[: idx + 3])
    return None


def _resolve_doc_source(
    workspace_root: Path,
    handoff_root: Path,
    selected: dict[str, str],
    key: str,
) -> tuple[str, Path] | tuple[str, None]:
    rel_path = str(selected.get(key) or "").strip()
    if not rel_path:
        return "", None
    raw = Path(rel_path).expanduser()
    if raw.is_absolute():
        return rel_path, raw.resolve()
    handoff_candidate = (handoff_root / raw).resolve()
    if handoff_candidate.exists():
        return rel_path, handoff_candidate
    return rel_path, (workspace_root / raw).resolve()


def _resolve_asset_source(
    workspace_root: Path,
    handoff_root: Path,
    rel_path: str,
) -> Path:
    raw = Path(rel_path).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    handoff_candidate = (handoff_root / raw).resolve()
    if handoff_candidate.exists():
        return handoff_candidate
    return (workspace_root / raw).resolve()


def _session_rel(workspace_root: Path, path: Path) -> str:
    return _safe_rel(path, workspace_root)


def _rewrite_scope_paths(paths: list[str], session_workspace_rel: Path) -> list[str]:
    out: list[str] = []
    for rel_path in paths:
        clean = str(Path(rel_path))
        if not clean or clean == ".":
            continue
        out.append((session_workspace_rel / clean).as_posix())
    return sorted(dict.fromkeys(out))


def _normalize_backend_names(raw_backends: Any) -> list[str]:
    if not isinstance(raw_backends, list):
        return []
    normalized: list[str] = []
    for item in raw_backends:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
            continue
        if isinstance(item, dict):
            raw_name = item.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                normalized.append(raw_name.strip())
    return sorted(dict.fromkeys(normalized))


def materialize_handoff_bundle(
    *,
    workspace_root: str | Path,
    session_root: str | Path,
    handoff_root: str | Path,
    selected: dict[str, str],
    allowlist_summary: dict[str, Any],
    design_assets: dict[str, Any],
    manifest_data: dict[str, Any] | None,
    source_index: dict[str, Any] | None,
    case_id: str,
    target_state: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = Path(workspace_root).expanduser().resolve()
    handoff = Path(handoff_root).expanduser().resolve()
    paths = _session_workspace_paths(workspace, Path(session_root).expanduser().resolve())
    session_root_path = paths["session_root"]
    session_workspace = paths["workspace_dir"]
    session_handoff_dir = paths["handoff_dir"]
    docs_dir = paths["docs_dir"]
    spec_out_dir = paths["spec_out_dir"]
    source_context_dir = session_handoff_dir / "source_context"
    session_workspace_rel = Path(_session_rel(workspace, session_workspace))

    doc_destinations = {
        "spec": spec_out_dir / "spec.md",
        "reqs": spec_out_dir / "reqs.md",
        "testplan": spec_out_dir / "testplan.md",
        "baseline_summary": docs_dir / "baseline_summary.md",
        "compat_constraints": docs_dir / "compat_constraints.md",
        "allowlist": docs_dir / "changed_files_allowlist.yaml",
    }

    copied_docs: dict[str, Any] = {}
    for key, dst in doc_destinations.items():
        rel_path, src = _resolve_doc_source(workspace, handoff, selected, key)
        if not src or not src.exists():
            raise ValueError(f"cannot materialize {key}: source file missing")
        meta = _copy_file(src, dst)
        copied_docs[key] = {
            "source_path": rel_path or str(src),
            "source_abs": meta["src_abs"],
            "dest_abs": meta["dst_abs"],
            "workspace_rel": _session_rel(workspace, dst),
            "sha256": meta["sha256"],
            "size": meta["size"],
        }

    copied_source_context: dict[str, Any] = {"reference_docs": []}
    source_index = source_index or {}
    reference_docs: list[dict[str, Any]] = []
    for item in source_index.get("reference_docs", []) if isinstance(source_index, dict) else []:
        abs_path = str(item.get("abs", "")).strip()
        if not abs_path:
            continue
        src = Path(abs_path).resolve()
        if not src.exists():
            continue
        rel_hint = str(item.get("handoff_rel", "")).strip()
        if rel_hint.startswith("source_requirements/"):
            rel_target = Path(rel_hint[len("source_requirements/"):])
        elif rel_hint and "/" in rel_hint:
            rel_target = Path(Path(rel_hint).name)
        else:
            rel_target = Path(src.name)
        dst = source_context_dir / "source_requirements" / rel_target
        meta = _copy_file(src, dst)
        reference_docs.append(
            {
                "source_abs": meta["src_abs"],
                "dest_abs": meta["dst_abs"],
                "workspace_rel": _session_rel(workspace, dst),
                "sha256": meta["sha256"],
                "size": meta["size"],
            }
        )
    copied_source_context["reference_docs"] = reference_docs

    copied_assets: dict[str, Any] = {}
    for key in ("rtl_file", "rtl_filelist", "tb_wrapper_file", "tb_py_file", "test_file"):
        rel_path = str(design_assets.get(key) or "").strip()
        if not rel_path:
            raise ValueError(f"cannot materialize {key}: missing path")
        src = _resolve_asset_source(workspace, handoff, rel_path)
        if not src.exists():
            raise ValueError(f"cannot materialize {key}: source file missing: {rel_path}")
        dst = (session_workspace / rel_path).resolve()
        _ensure_within(dst, session_workspace, key)
        meta = _copy_file(src, dst)
        copied_assets[key] = {
            "source_path": rel_path,
            "source_abs": meta["src_abs"],
            "dest_abs": meta["dst_abs"],
            "workspace_rel": _session_rel(workspace, dst),
            "sha256": meta["sha256"],
            "size": meta["size"],
        }

    verification = dict(manifest_data.get("verification", {})) if isinstance(manifest_data, dict) else {}
    backends = _normalize_backend_names(verification.get("backends"))
    if not backends:
        backends = ["verilator"]
    regression_modules = verification.get("regression_modules")
    if not isinstance(regression_modules, list):
        regression_modules = []
    if not regression_modules and str(design_assets.get("test_module") or "").strip():
        regression_modules = [str(design_assets.get("test_module")).strip()]
    smoke_testcase = str(verification.get("smoke_testcase") or design_assets.get("smoke_testcase") or "run_basic").strip()

    materialized_manifest = {
        "schema_version": "artifact_handoff_manifest/v1",
        "case_id": case_id,
        "delivery_state": target_state,
        "docs": {
            "spec_file": copied_docs["spec"]["workspace_rel"],
            "reqs_file": copied_docs["reqs"]["workspace_rel"],
            "testplan_file": copied_docs["testplan"]["workspace_rel"],
            "baseline_summary_file": copied_docs["baseline_summary"]["workspace_rel"],
            "compat_constraints_file": copied_docs["compat_constraints"]["workspace_rel"],
            "allowlist_file": copied_docs["allowlist"]["workspace_rel"],
        },
        "design_assets": {
            "rtl_file": copied_assets["rtl_file"]["workspace_rel"],
            "rtl_filelist": copied_assets["rtl_filelist"]["workspace_rel"],
            "tb_wrapper_file": copied_assets["tb_wrapper_file"]["workspace_rel"],
            "tb_py_file": copied_assets["tb_py_file"]["workspace_rel"],
            "test_file": copied_assets["test_file"]["workspace_rel"],
            "top_level": str(design_assets.get("top_level") or "").strip(),
            "test_module": str(design_assets.get("test_module") or "").strip(),
            "smoke_testcase": smoke_testcase,
        },
        "change_scope": {
            "allowed_modify": _rewrite_scope_paths(
                list(allowlist_summary.get("allowed_modify", [])),
                session_workspace_rel,
            ),
            "allowed_create": _rewrite_scope_paths(
                list(allowlist_summary.get("allowed_create", [])),
                session_workspace_rel,
            ),
            "forbidden_actions": list(allowlist_summary.get("forbidden_actions", [])),
        },
        "verification": {
            "backends": backends,
            "smoke_testcase": smoke_testcase,
            "regression_modules": regression_modules,
        },
        "materialization": {
            "session_root": _session_rel(workspace, session_root_path),
            "session_workspace": _session_rel(workspace, session_workspace),
            "source_handoff_root": str(handoff),
        },
    }
    source_context: dict[str, Any] = {}
    reference_doc_paths = [
        str(item.get("workspace_rel", "")).strip()
        for item in copied_source_context.get("reference_docs", [])
        if str(item.get("workspace_rel", "")).strip()
    ]
    if reference_doc_paths:
        source_context["reference_docs"] = reference_doc_paths
    semantic_mode = str(source_index.get("semantic_review_mode", "required")).strip() or "required"
    if source_context or semantic_mode:
        if semantic_mode:
            source_context["semantic_review_mode"] = semantic_mode
        materialized_manifest["source_context"] = source_context

    report = {
        "schema_version": "handoff_materialization/v1",
        "case_id": case_id,
        "target_state": target_state,
        "workspace_root": str(workspace),
        "handoff_root": str(handoff),
        "session_root": _session_rel(workspace, session_root_path),
        "session_workspace": _session_rel(workspace, session_workspace),
        "session_handoff_dir": _session_rel(workspace, session_handoff_dir),
        "copied_docs": copied_docs,
        "copied_source_context": copied_source_context,
        "copied_assets": copied_assets,
        "materialized_manifest_preview": materialized_manifest,
    }
    return report, materialized_manifest


def write_materialization_outputs(
    *,
    workspace_root: str | Path,
    session_root: str | Path,
    report: dict[str, Any],
    materialized_manifest: dict[str, Any],
) -> dict[str, str]:
    workspace = Path(workspace_root).expanduser().resolve()
    paths = _session_workspace_paths(workspace, Path(session_root).expanduser().resolve())
    handoff_dir = paths["handoff_dir"]
    handoff_dir.mkdir(parents=True, exist_ok=True)
    report_path = handoff_dir / "handoff_materialization.json"
    manifest_path = handoff_dir / "handoff_manifest.materialized.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(materialized_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "report_path": str(report_path),
        "manifest_path": str(manifest_path),
        "report_rel": _session_rel(workspace, report_path),
        "manifest_rel": _session_rel(workspace, manifest_path),
    }

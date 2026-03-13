#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from handoff_utils import HandoffError, build_handoff_context, load_handoff_manifest
from handoff_materialize import (
    infer_session_root_from_path,
    materialize_handoff_bundle,
    write_materialization_outputs,
)
from handoff_prompt_utils import (
    DEFAULT_SCHEMA_PATH,
    build_handoff_requirements_prompt,
    load_handoff_schema,
)


SCHEMA_VERSION = "handoff_intake_audit/v1"
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "sim_build",
    "artifacts",
    "logs",
}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
DOC_CATEGORIES = (
    "manifest",
    "spec",
    "reqs",
    "testplan",
    "baseline_summary",
    "compat_constraints",
    "allowlist",
)


@dataclass
class Gap:
    code: str
    severity: str
    message: str
    suggestion: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def _safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _resolve_input_path(base: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _resolve_existing_path(raw_path: str, search_roots: list[Path]) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    seen: set[str] = set()
    for root in search_roots:
        candidate = (root / path).resolve()
        if str(candidate) in seen:
            continue
        seen.add(str(candidate))
        if candidate.exists():
            return candidate
    return (search_roots[0] / path).resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_rules(config_path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise SystemExit(f"[HANDOFF][FAIL] failed to parse rules file {config_path}: {exc}") from exc
    rules = raw.get("incremental_handoff")
    if not isinstance(rules, dict):
        raise SystemExit(f"[HANDOFF][FAIL] missing incremental_handoff rules in {config_path}")
    return rules


def scan_handoff_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def match_category(rel_path: str, patterns: list[str]) -> bool:
    filename = Path(rel_path).name
    lowered = rel_path.lower()
    lowered_name = filename.lower()
    for pattern in patterns:
        pattern_low = pattern.lower()
        if fnmatch.fnmatch(lowered_name, pattern_low) or fnmatch.fnmatch(lowered, pattern_low):
            return True
    return False


def classify_files(files: list[Path], root: Path, rules: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    category_rules = rules.get("file_categories", {})
    inventory: list[dict[str, Any]] = []
    buckets: dict[str, list[str]] = {category: [] for category in DOC_CATEGORIES}
    for path in files:
        rel_path = _safe_rel(path, root)
        categories: list[str] = []
        for category in DOC_CATEGORIES:
            cfg = category_rules.get(category, {})
            patterns = cfg.get("patterns", [])
            if patterns and match_category(rel_path, patterns):
                categories.append(category)
                buckets[category].append(rel_path)
        inventory.append(
            {
                "path": rel_path,
                "size": path.stat().st_size,
                "suffix": path.suffix.lower(),
                "categories": categories,
            }
        )
    return inventory, buckets


def rank_candidate(rel_path: str, category: str, category_rules: dict[str, Any]) -> tuple[int, int, str]:
    filename = Path(rel_path).name.lower()
    depth = len(Path(rel_path).parts)
    patterns = category_rules.get(category, {}).get("patterns", [])
    pattern_rank = len(patterns) + 1
    for idx, pattern in enumerate(patterns):
        if match_category(rel_path, [pattern]):
            pattern_rank = idx
            break
    return (pattern_rank, depth, filename)


def choose_selected_files(buckets: dict[str, list[str]], rules: dict[str, Any]) -> dict[str, str]:
    category_rules = rules.get("file_categories", {})
    selected: dict[str, str] = {}
    for category, paths in buckets.items():
        if not paths:
            continue
        selected[category] = sorted(paths, key=lambda p: rank_candidate(p, category, category_rules))[0]
    return selected


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def evaluate_markdown_doc(category: str, path: Path, rules: dict[str, Any]) -> dict[str, Any]:
    text = read_text(path)
    text_low = text.lower()
    heading_count = sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))
    cfg = rules.get("content_rules", {}).get(category, {})
    keywords = cfg.get("keywords", [])
    min_hits = int(cfg.get("min_keyword_hits", 1))
    hits = [keyword for keyword in keywords if keyword.lower() in text_low]
    passed = heading_count >= 1 and len(hits) >= min_hits
    return {
        "path": str(path),
        "category": category,
        "passed": passed,
        "heading_count": heading_count,
        "keyword_hits": hits,
        "required_keyword_hits": min_hits,
    }


def parse_allowlist(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return None, f"failed to parse YAML: {exc}"
    if not isinstance(data, dict):
        return None, "allowlist must be a YAML object"
    return data, None


def _extract_path_items(raw: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if isinstance(item, dict):
            candidate = item.get("path")
            if isinstance(candidate, str) and candidate.strip():
                out.append(candidate.strip())
    return out


def _extract_action_items(raw: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if isinstance(item, dict) and item:
            parts = []
            for key, value in item.items():
                if isinstance(value, str) and value.strip():
                    parts.append(f"{key}:{value.strip()}")
                else:
                    parts.append(str(key))
            if parts:
                out.append("; ".join(parts))
    return out


def build_allowlist_summary(
    allowlist_path: Path,
    handoff_root: Path,
    workspace: Path,
) -> tuple[dict[str, Any], list[Gap]]:
    data, error = parse_allowlist(allowlist_path)
    summary: dict[str, Any] = {
        "path": str(allowlist_path),
        "parsed": error is None,
        "allowed_modify": [],
        "allowed_create": [],
        "forbidden_actions": [],
        "root_resolved": [],
        "workspace_resolved": [],
    }
    gaps: list[Gap] = []
    if error:
        gaps.append(
            Gap(
                "allowlist_parse_failed",
                "error",
                f"allowlist YAML is invalid: {error}",
                "Rewrite changed_files_allowlist.yaml as a YAML object with allowed_modify / allowed_create / forbidden_actions.",
            )
        )
        summary["error"] = error
        return summary, gaps

    allowed_modify = _extract_path_items(data.get("allowed_modify"))
    allowed_create = _extract_path_items(data.get("allowed_create"))
    forbidden_actions = _extract_action_items(data.get("forbidden_actions"))
    summary["allowed_modify"] = allowed_modify
    summary["allowed_create"] = allowed_create
    summary["forbidden_actions"] = forbidden_actions

    if not allowed_modify:
        gaps.append(
            Gap(
                "allowlist_missing_allowed_modify",
                "error",
                "allowlist does not declare any allowed_modify paths",
                "Add allowed_modify entries for every RTL/TB/test file that downstream stages may touch.",
            )
        )
    if not forbidden_actions:
        gaps.append(
            Gap(
                "allowlist_missing_forbidden_actions",
                "warning",
                "allowlist does not declare forbidden_actions",
                "Add forbidden_actions so downstream agents know what not to change.",
            )
        )

    for rel_path in allowed_modify + allowed_create:
        root_path = (handoff_root / rel_path).resolve()
        workspace_path = (workspace / rel_path).resolve()
        summary["root_resolved"].append(
            {
                "path": rel_path,
                "abs": str(root_path),
                "exists": root_path.exists(),
            }
        )
        summary["workspace_resolved"].append(
            {
                "path": rel_path,
                "abs": str(workspace_path),
                "exists": workspace_path.exists(),
            }
        )
    return summary, gaps


def _candidate_list(paths: list[str], predicate) -> list[str]:
    out: list[str] = []
    for rel_path in paths:
        if predicate(rel_path):
            out.append(rel_path)
    return sorted(dict.fromkeys(out))


def _looks_like_test_file(rel_path: str) -> bool:
    name = Path(rel_path).name
    return rel_path.endswith(".py") and (name.startswith("test_") or "/tests/" in f"/{rel_path}")


def _looks_like_tb_py(rel_path: str) -> bool:
    return rel_path.endswith(".py") and "/tb/" in f"/{rel_path}" and not _looks_like_test_file(rel_path)


def _looks_like_tb_wrapper(rel_path: str) -> bool:
    return rel_path.endswith((".sv", ".v")) and "/tb/hdl/" in f"/{rel_path}"


def _looks_like_rtl(rel_path: str) -> bool:
    wrapped = f"/{rel_path}"
    return rel_path.endswith((".sv", ".v")) and "/rtl/" in wrapped and "/tb/" not in wrapped


def _looks_like_filelist(rel_path: str) -> bool:
    return rel_path.endswith(".f")


def _select_single(name: str, items: list[str], gaps: list[Gap], requirement: str) -> str:
    if not items:
        gaps.append(
            Gap(
                f"{name}_missing",
                "error",
                f"no {requirement} candidate could be inferred",
                f"Provide a manifest or include a unique {requirement} path in changed_files_allowlist.yaml.",
            )
        )
        return ""
    if len(items) > 1:
        gaps.append(
            Gap(
                f"{name}_ambiguous",
                "error",
                f"multiple {requirement} candidates were found: {', '.join(items)}",
                f"Disambiguate {requirement} in a manifest or narrow changed_files_allowlist.yaml.",
            )
        )
        return ""
    return items[0]


def _module_name_from_tb_wrapper(path: Path) -> str:
    text = read_text(path)
    match = re.search(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.MULTILINE)
    if match:
        return match.group(1)
    return path.stem


def _test_module_from_path(rel_path: str) -> str:
    candidate = Path(rel_path)
    if candidate.suffix == ".py":
        candidate = candidate.with_suffix("")
    parts = [part for part in candidate.parts if part and part != "__init__"]
    return ".".join(parts)


def _smoke_testcase_from_file(path: Path) -> str:
    text = read_text(path)
    matches = re.findall(
        r"@cocotb\.test(?:\([^)]*\))?\s*[\r\n]+(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)",
        text,
        flags=re.MULTILINE,
    )
    if not matches:
        return ""
    for name in matches:
        if name == "run_basic":
            return name
    return matches[0]


def _resolve_asset_probe_path(workspace: Path, handoff_root: Path, rel_path: str) -> Path:
    """Resolve the best available file for intake-time inspection.

    Prefer the imported handoff bundle, because it represents the upstream AI's
    current delivery. Fall back to the existing workspace copy only when the
    bundle does not contain the asset.
    """
    handoff_path = (handoff_root / rel_path).resolve()
    if handoff_path.exists():
        return handoff_path
    return (workspace / rel_path).resolve()


def infer_design_assets(
    allowlist_summary: dict[str, Any],
    workspace: Path,
    handoff_root: Path,
    *,
    manifest_data: dict[str, Any] | None = None,
    materialize_into_session: bool = False,
) -> tuple[dict[str, Any], list[Gap]]:
    manifest_design_assets = (
        manifest_data.get("design_assets", {}) if isinstance(manifest_data, dict) else {}
    )
    manifest_verification = (
        manifest_data.get("verification", {}) if isinstance(manifest_data, dict) else {}
    )
    paths = list(allowlist_summary.get("allowed_modify", [])) + list(
        allowlist_summary.get("allowed_create", [])
    )
    gaps: list[Gap] = []
    def _explicit_or_inferred(key: str, candidates: list[str], label: str) -> str:
        raw = manifest_design_assets.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return _select_single(key, candidates, gaps, label)

    rtl_file = _explicit_or_inferred("rtl_file", _candidate_list(paths, _looks_like_rtl), "RTL file")
    rtl_filelist = _explicit_or_inferred(
        "rtl_filelist", _candidate_list(paths, _looks_like_filelist), "filelist"
    )
    tb_wrapper_file = _explicit_or_inferred(
        "tb_wrapper_file", _candidate_list(paths, _looks_like_tb_wrapper), "TB wrapper"
    )
    tb_py_file = _explicit_or_inferred(
        "tb_py_file", _candidate_list(paths, _looks_like_tb_py), "cocotb support Python file"
    )
    test_file = _explicit_or_inferred(
        "test_file", _candidate_list(paths, _looks_like_test_file), "cocotb test file"
    )

    assets: dict[str, Any] = {
        "rtl_file": rtl_file,
        "rtl_filelist": rtl_filelist,
        "tb_wrapper_file": tb_wrapper_file,
        "tb_py_file": tb_py_file,
        "test_file": test_file,
        "top_level": str(manifest_design_assets.get("top_level") or "").strip(),
        "test_module": str(manifest_design_assets.get("test_module") or "").strip(),
        "smoke_testcase": (
            str(manifest_design_assets.get("smoke_testcase") or "").strip()
            or str(manifest_verification.get("smoke_testcase") or "").strip()
        ),
        "resolution": {},
    }

    for key in ("rtl_file", "rtl_filelist", "tb_wrapper_file", "tb_py_file", "test_file"):
        rel_path = assets[key]
        if not rel_path:
            continue
        workspace_path = (workspace / rel_path).resolve()
        handoff_path = (handoff_root / rel_path).resolve()
        assets["resolution"][key] = {
            "workspace": {"path": rel_path, "abs": str(workspace_path), "exists": workspace_path.exists()},
            "handoff_root": {"path": rel_path, "abs": str(handoff_path), "exists": handoff_path.exists()},
        }
        if not workspace_path.exists() and handoff_path.exists():
            if materialize_into_session:
                gaps.append(
                    Gap(
                        f"{key}_will_be_materialized",
                        "info",
                        f"{key} exists under the handoff root and will be materialized into the session workspace: {rel_path}",
                        "No manual copy is required if session-root materialization is enabled.",
                    )
                )
            else:
                gaps.append(
                    Gap(
                        f"{key}_outside_workspace",
                        "error",
                        f"{key} exists under the handoff root but not in the current pipeline workspace: {rel_path}",
                        "Copy or map the referenced design asset into the current workspace, then regenerate the manifest.",
                    )
                )
        if not workspace_path.exists() and not handoff_path.exists():
            gaps.append(
                Gap(
                    f"{key}_not_found",
                    "error",
                    f"{key} does not exist in the handoff root or the current workspace: {rel_path}",
                    "Fix the file path in changed_files_allowlist.yaml or include the missing asset.",
                )
            )

    if tb_wrapper_file and not assets["top_level"]:
        tb_wrapper_path = _resolve_asset_probe_path(workspace, handoff_root, tb_wrapper_file)
        if tb_wrapper_path.exists():
            assets["top_level"] = _module_name_from_tb_wrapper(tb_wrapper_path)
        else:
            assets["top_level"] = Path(tb_wrapper_file).stem

    if test_file:
        if not assets["test_module"]:
            assets["test_module"] = _test_module_from_path(test_file)
        test_probe_path = _resolve_asset_probe_path(workspace, handoff_root, test_file)
        smoke_test = assets["smoke_testcase"]
        if not smoke_test and test_probe_path.exists():
            smoke_test = _smoke_testcase_from_file(test_probe_path)
        if smoke_test:
            assets["smoke_testcase"] = smoke_test
        else:
            gaps.append(
                Gap(
                    "smoke_testcase_missing",
                    "warning",
                    f"could not infer a cocotb smoke testcase from {test_file}",
                    "Declare verification.smoke_testcase explicitly in a handoff manifest.",
                )
            )

    return assets, gaps


def build_candidate_manifest(
    case_id: str,
    workspace: Path,
    handoff_root: Path,
    selected: dict[str, str],
    allowlist_summary: dict[str, Any],
    design_assets: dict[str, Any],
    source_index: dict[str, Any],
) -> dict[str, Any]:
    def doc_workspace_rel(category: str) -> str:
        rel_path = selected.get(category, "")
        if not rel_path:
            return ""
        return _safe_rel((handoff_root / rel_path).resolve(), workspace)

    reqs_file = doc_workspace_rel("reqs")
    testplan_file = doc_workspace_rel("testplan")
    spec_file = doc_workspace_rel("spec")
    baseline_summary_file = doc_workspace_rel("baseline_summary")
    compat_constraints_file = doc_workspace_rel("compat_constraints")
    allowlist_file = doc_workspace_rel("allowlist")

    manifest = {
        "schema_version": "artifact_handoff_manifest/v1",
        "case_id": case_id,
        "delivery_state": "verify_ready",
        "docs": {
            "spec_file": spec_file,
            "reqs_file": reqs_file,
            "testplan_file": testplan_file,
            "baseline_summary_file": baseline_summary_file,
            "compat_constraints_file": compat_constraints_file,
            "allowlist_file": allowlist_file,
        },
        "design_assets": {
            "rtl_file": design_assets["rtl_file"],
            "rtl_filelist": design_assets["rtl_filelist"],
            "tb_wrapper_file": design_assets["tb_wrapper_file"],
            "tb_py_file": design_assets["tb_py_file"],
            "test_file": design_assets["test_file"],
            "top_level": design_assets["top_level"],
            "test_module": design_assets["test_module"],
            "smoke_testcase": design_assets["smoke_testcase"],
        },
        "change_scope": {
            "allowed_modify": allowlist_summary.get("allowed_modify", []),
            "allowed_create": allowlist_summary.get("allowed_create", []),
            "forbidden_actions": allowlist_summary.get("forbidden_actions", []),
        },
        "verification": {
            "backends": ["verilator"],
            "smoke_testcase": design_assets["smoke_testcase"] or "run_basic",
            "regression_modules": [design_assets["test_module"]] if design_assets["test_module"] else [],
        },
    }
    source_context: dict[str, Any] = {}
    reference_docs = [
        str(item.get("handoff_rel", "")).strip()
        for item in source_index.get("reference_docs", [])
        if str(item.get("handoff_rel", "")).strip()
    ]
    if reference_docs:
        source_context["reference_docs"] = reference_docs
    semantic_mode = str(source_index.get("semantic_review_mode", "required")).strip()
    if semantic_mode:
        source_context["semantic_review_mode"] = semantic_mode
    if source_context:
        manifest["source_context"] = source_context
    return manifest


def validate_manifest_candidate(
    manifest_data: dict[str, Any],
    manifest_path: Path,
    workspace: Path,
    target_state: str,
) -> tuple[dict[str, Any], Gap | None]:
    try:
        context = build_handoff_context(
            manifest_data,
            manifest_path,
            workspace,
            expected_delivery_state=target_state,
        )
    except HandoffError as exc:
        return {}, Gap(
            "candidate_manifest_invalid",
            "error",
            f"candidate manifest failed normalization: {exc}",
            "Add or correct the missing files/fields, then rerun handoff_intake_validator.",
        )
    return context, None


def dedupe_gaps(gaps: list[Gap]) -> list[Gap]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Gap] = []
    for gap in gaps:
        key = (gap.code, gap.message, gap.suggestion)
        if key in seen:
            continue
        seen.add(key)
        out.append(gap)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda item: (severity_order.get(item.severity, 9), item.code))


def infer_case_id(handoff_root: Path, selected: dict[str, str], manifest_data: dict[str, Any] | None) -> str:
    if manifest_data:
        case_id = manifest_data.get("case_id")
        if isinstance(case_id, str) and case_id.strip():
            return case_id.strip()
    for candidate in (handoff_root.name, selected.get("baseline_summary", "")):
        if isinstance(candidate, str) and candidate:
            stem = Path(candidate).stem.replace(" ", "_")
            if stem:
                return stem
    return "handoff_case"


def determine_inferred_state(
    target_state: str,
    selected: dict[str, str],
    design_assets: dict[str, Any],
    gaps: list[Gap],
) -> str:
    has_docs = all(selected.get(name) for name in ("baseline_summary", "compat_constraints", "allowlist"))
    has_verify_docs = all(selected.get(name) for name in ("spec", "reqs", "testplan"))
    has_assets = all(design_assets.get(name) for name in ("rtl_file", "rtl_filelist", "tb_wrapper_file", "tb_py_file", "test_file"))
    if not has_docs:
        return "insufficient"
    if target_state == "verify_ready" and has_docs and has_verify_docs and has_assets:
        if not any(gap.severity == "error" for gap in gaps):
            return "verify_ready"
    return "analysis_only"


def _selected_path(root: Path, selected: dict[str, str], key: str) -> Path | None:
    rel_path = selected.get(key)
    if not rel_path:
        return None
    return (root / rel_path).resolve()


def _resolve_selected_doc_path(workspace: Path, handoff_root: Path, rel_path: str) -> Path:
    direct = Path(rel_path).expanduser()
    if direct.is_absolute():
        return direct.resolve()
    root_path = (handoff_root / rel_path).resolve()
    if root_path.exists():
        return root_path
    return (workspace / rel_path).resolve()


def collect_doc_checks(
    workspace: Path,
    handoff_root: Path,
    selected: dict[str, str],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[Gap]]:
    checks: list[dict[str, Any]] = []
    gaps: list[Gap] = []
    for category in ("baseline_summary", "compat_constraints", "reqs", "testplan"):
        rel_path = selected.get(category)
        if not rel_path:
            continue
        path = _resolve_selected_doc_path(workspace, handoff_root, rel_path)
        if not path:
            continue
        result = evaluate_markdown_doc(category, path, rules)
        checks.append(result)
        if not result["passed"]:
            gaps.append(
                Gap(
                    f"{category}_content_weak",
                    "warning",
                    f"{category} content is weak or incomplete: {selected[category]}",
                    f"Expand {Path(selected[category]).name} so it clearly documents the expected {category.replace('_', ' ')} content.",
                )
            )
    return checks, gaps


def collect_required_doc_gaps(selected: dict[str, str], rules: dict[str, Any], target_state: str) -> list[Gap]:
    required = rules.get("required_docs", {}).get(target_state, [])
    gaps: list[Gap] = []
    for category in required:
        if selected.get(category):
            continue
        suggestion = {
            "spec": "Add spec.md or point the validator at an existing spec file.",
            "reqs": "Add reqs.md or delta_spec.md with the required behavior delta.",
            "testplan": "Add testplan.md or testplan_delta.md with testcase intent and acceptance checks.",
            "baseline_summary": "Add baseline_summary.md describing the baseline design and patch intent.",
            "compat_constraints": "Add compat_constraints.md describing what must remain compatible.",
            "allowlist": "Add changed_files_allowlist.yaml describing allowed_modify / allowed_create / forbidden_actions.",
        }.get(category, f"Add a {category} document.")
        gaps.append(
            Gap(
                f"{category}_missing",
                "error",
                f"missing required {category} document for {target_state}",
                suggestion,
            )
        )
    return gaps


def collect_required_asset_gaps(design_assets: dict[str, Any], rules: dict[str, Any], target_state: str) -> list[Gap]:
    required = rules.get("required_design_assets", {}).get(target_state, [])
    gaps: list[Gap] = []
    for field in required:
        if design_assets.get(field):
            continue
        gaps.append(
            Gap(
                f"{field}_missing",
                "error",
                f"missing required {field} for {target_state}",
                f"Declare {field} explicitly in a handoff manifest or make it uniquely inferable from the allowlist.",
            )
        )
    return gaps


def build_gap_report(audit: dict[str, Any]) -> str:
    lines = [
        "# Handoff Intake Report",
        "",
        f"- Status: `{audit['status']}`",
        f"- Target State: `{audit['target_state']}`",
        f"- Inferred State: `{audit['inferred_state']}`",
        f"- Handoff Root: `{audit['handoff_root']['abs']}`",
        f"- Semantic Review Mode: `{audit.get('semantic_review_mode', 'required')}`",
        f"- Semantic Review Requested: `{audit.get('semantic_review_requested', False)}`",
        "",
        "## Selected Files",
        "",
    ]
    for category, rel_path in sorted(audit["selected_files"].items()):
        lines.append(f"- `{category}`: `{rel_path}`")
    if not audit["selected_files"]:
        lines.append("- none")

    lines.extend(["", "## Gaps", ""])
    if audit["gaps"]:
        for gap in audit["gaps"]:
            lines.append(f"- `{gap['severity']}` `{gap['code']}`: {gap['message']}")
            lines.append(f"  - fix: {gap['suggestion']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Outputs", ""])
    for key, rel_path in audit["outputs"].items():
        if rel_path:
            lines.append(f"- `{key}`: `{rel_path}`")
    lines.append("")
    return "\n".join(lines)


def build_repair_prompt(audit: dict[str, Any]) -> str:
    selected = audit["selected_files"]
    missing_docs = sorted({gap["code"] for gap in audit["gaps"] if gap["code"].endswith("_missing")})
    lines = [
        "You are preparing an incremental artifact handoff for Open Chip Flow.",
        "",
        "The current handoff intake audit did not meet the required verify_ready standard.",
        "",
        "Keep already-good files. Only add the missing information or correct the weak files.",
        "",
        "Current detected files:",
    ]
    if selected:
        for category, rel_path in sorted(selected.items()):
            lines.append(f"- {category}: {rel_path}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "Required output filenames:",
            "- source_requirements/... for original requirement/source docs",
            "- baseline_summary.md",
            "- compat_constraints.md",
            "- changed_files_allowlist.yaml",
            "- spec.md",
            "- reqs.md or delta_spec.md",
            "- testplan.md or testplan_delta.md",
            "- handoff_manifest.json when the handoff is verify_ready",
            "- rtl/... for RTL sources",
            "- filelists/... for .f filelists",
            "- tb/hdl/... for SV TB wrappers",
            "- tb/*.py for cocotb helper Python files",
            "- tests/*.py for cocotb tests",
            "",
            "Manifest requirements:",
            "- schema_version must be artifact_handoff_manifest/v1",
            "- case_id must be a stable non-empty string",
            "- delivery_state must be verify_ready",
            "- docs must point to spec/reqs/testplan/baseline/compat/allowlist",
            "- design_assets must point to rtl_file, rtl_filelist, tb_wrapper_file, tb_py_file, test_file, top_level, test_module, smoke_testcase",
            "- change_scope must contain allowed_modify, allowed_create, forbidden_actions",
            "- verification must contain backends and smoke_testcase",
            "- source_context should identify source_requirements/* when semantic review is enabled",
            "",
            "Audit findings to fix:",
        ]
    )
    for gap in audit["gaps"]:
        lines.append(f"- [{gap['severity']}] {gap['message']}")
        lines.append(f"  Fix: {gap['suggestion']}")

    if not audit["gaps"]:
        lines.append("- No blocking gaps. Regenerate the handoff manifest in the standard format.")

    lines.extend(
        [
            "",
            "Do not regenerate unrelated files.",
            "Do not rename design assets unless the manifest and allowlist are updated consistently.",
            "If multiple design assets exist, disambiguate them explicitly in handoff_manifest.json instead of leaving them implicit.",
            "Use the exact target-relative layout rtl/... filelists/... tb/... tests/... so OpenChipFlow can materialize the bundle automatically.",
        ]
    )
    if missing_docs:
        lines.extend(
            [
                "",
                "Missing categories detected:",
                *[f"- {code}" for code in missing_docs],
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def remove_path_if_exists(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except IsADirectoryError:
        pass


def _resolve_optional_path(raw_path: str, search_roots: list[Path]) -> Path | None:
    raw = raw_path.strip()
    if not raw:
        return None
    return _resolve_existing_path(raw, search_roots)


def _normalize_semantic_review_mode(raw: str, default_mode: str) -> str:
    mode = (raw or "").strip().lower()
    if mode in {"off", "auto", "required"}:
        return mode
    return default_mode


def _path_info(path: Path | None, *, workspace: Path, handoff_root: Path, source: str, label: str) -> dict[str, Any]:
    if not path:
        return {
            "label": label,
            "source": source,
            "input": "",
            "abs": "",
            "workspace_rel": "",
            "handoff_rel": "",
            "exists": False,
        }
    resolved = path.resolve()
    return {
        "label": label,
        "source": source,
        "input": str(path),
        "abs": str(resolved),
        "workspace_rel": _safe_rel(resolved, workspace),
        "handoff_rel": _safe_rel(resolved, handoff_root),
        "exists": resolved.exists(),
    }


def _find_first_matching_file(root: Path, patterns: list[str]) -> Path | None:
    if not root.exists():
        return None
    matches: list[Path] = []
    for path in scan_handoff_files(root):
        rel_path = _safe_rel(path, root)
        if match_category(rel_path, patterns):
            matches.append(path.resolve())
    return sorted(matches, key=lambda item: (_safe_rel(item, root).count("/"), item.name.lower()))[0] if matches else None


def _find_reference_root(root: Path, dir_names: list[str]) -> Path | None:
    if not root.exists():
        return None
    candidates: list[Path] = []
    wanted = {name.strip().lower() for name in dir_names if isinstance(name, str) and name.strip()}
    for path in sorted(root.rglob("*")):
        if not path.is_dir():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.name.lower() in wanted:
            candidates.append(path.resolve())
    return sorted(candidates, key=lambda item: (_safe_rel(item, root).count("/"), item.name.lower()))[0] if candidates else None


def _collect_reference_docs(reference_root: Path) -> list[Path]:
    docs: list[Path] = []
    if not reference_root.exists() or not reference_root.is_dir():
        return docs
    for path in sorted(reference_root.rglob("*")):
        rel_parts = path.relative_to(reference_root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            docs.append(path.resolve())
    return docs


def discover_source_context(
    *,
    workspace: Path,
    handoff_root: Path,
    manifest_data: dict[str, Any] | None,
    search_roots: list[Path],
    rules: dict[str, Any],
    explicit_source_requirements_root: str,
    explicit_semantic_review_mode: str,
) -> tuple[dict[str, Any], list[Gap]]:
    source_rules = rules.get("source_context", {}) if isinstance(rules, dict) else {}
    manifest_source = manifest_data.get("source_context", {}) if isinstance(manifest_data, dict) else {}
    default_mode = str(rules.get("semantic_review_mode_default", "required")).strip().lower() or "required"
    mode = _normalize_semantic_review_mode(
        explicit_semantic_review_mode or str(manifest_source.get("semantic_review_mode", "")),
        default_mode,
    )
    handoff_search_roots = [handoff_root] + [root for root in search_roots if root != handoff_root]

    reference_root: Path | None = None
    reference_root_source = "none"
    reference_docs: list[Path] = []
    manifest_reference_docs = manifest_source.get("reference_docs")
    if explicit_source_requirements_root.strip():
        reference_root = _resolve_existing_path(explicit_source_requirements_root.strip(), handoff_search_roots)
        reference_root_source = "explicit"
    else:
        dir_names = [
            str(item).strip()
            for item in source_rules.get("reference_dir_names", [])
            if isinstance(item, str) and item.strip()
        ]
        if dir_names:
            reference_root = _find_reference_root(handoff_root, dir_names)
            if reference_root:
                reference_root_source = "bundle"
    if reference_root:
        reference_docs = _collect_reference_docs(reference_root)

    if isinstance(manifest_reference_docs, list):
        for raw_doc in manifest_reference_docs:
            if not isinstance(raw_doc, str) or not raw_doc.strip():
                continue
            candidate = _resolve_existing_path(raw_doc.strip(), handoff_search_roots)
            if candidate.exists():
                reference_docs.append(candidate)
        if manifest_reference_docs and reference_root_source == "none":
            reference_root_source = "manifest_docs"

    unique_docs: list[Path] = []
    seen_docs: set[str] = set()
    for doc in reference_docs:
        key = str(doc.resolve())
        if key in seen_docs:
            continue
        seen_docs.add(key)
        unique_docs.append(doc.resolve())
    reference_docs = unique_docs

    reference_root_info = _path_info(
        reference_root,
        workspace=workspace,
        handoff_root=handoff_root,
        source=reference_root_source,
        label="source_requirements_root",
    )
    reference_doc_items = [
        _path_info(path, workspace=workspace, handoff_root=handoff_root, source=reference_root_source, label="reference_doc")
        for path in reference_docs
    ]

    gaps: list[Gap] = []
    has_reference_docs = any(item["exists"] for item in reference_doc_items)
    if mode == "required" and not has_reference_docs:
        gaps.append(
            Gap(
                "source_requirements_missing",
                "error",
                "semantic review is required, but no source requirement documents were discovered",
                "Add source_requirements/ with the original requirement/source docs used by the upstream AI.",
            )
        )
    elif mode == "auto" and not has_reference_docs:
        gaps.append(
            Gap(
                "source_requirements_missing",
                "info",
                "no source requirement documents were discovered for semantic review",
                "Add source_requirements/ with the original requirement/source docs used by the upstream AI.",
            )
        )

    available = has_reference_docs
    return (
        {
            "schema_version": "handoff_source_index/v1",
            "generated_at": datetime.now().isoformat(),
            "semantic_review_mode": mode,
            "available": available,
            "reference_root": reference_root_info,
            "reference_docs": reference_doc_items,
        },
        gaps,
    )


def semantic_review_should_run(
    *,
    semantic_review_mode: str,
    source_index: dict[str, Any],
    selected: dict[str, str],
) -> tuple[bool, str]:
    mode = _normalize_semantic_review_mode(semantic_review_mode, "required")
    if mode == "off":
        return False, "semantic_review_mode=off"
    if not source_index.get("available"):
        return False, "source context unavailable"
    required_docs = ("baseline_summary", "compat_constraints", "reqs", "testplan")
    missing_docs = [name for name in required_docs if not str(selected.get(name) or "").strip()]
    if missing_docs:
        return False, f"missing review inputs: {', '.join(missing_docs)}"
    return True, "ready"


def build_semantic_review_request(
    *,
    workspace: Path,
    handoff_root: Path,
    source_index: dict[str, Any],
    selected: dict[str, str],
    allowlist_summary: dict[str, Any],
    design_assets: dict[str, Any],
    manifest_validation: dict[str, Any],
    contract_audit: dict[str, Any],
) -> str:
    def _doc_line(name: str) -> str:
        rel_path = str(selected.get(name) or "").strip()
        if not rel_path:
            return f"- {name}: <missing>"
        resolved = _resolve_selected_doc_path(workspace, handoff_root, rel_path)
        return f"- {name}: {resolved}"

    lines = [
        "# Handoff Semantic Review Request",
        "",
        "Review this handoff bundle as the downstream OpenChipFlow reviewer.",
        "The goal is to decide whether the handoff content actually satisfies the original incremental task intent, not just whether the files exist.",
        "",
        "## Required outputs",
        "",
        "- Write structured verdict JSON to the semantic_review_json path provided in the outer role prompt.",
        "- Write a readable markdown review to the semantic_review_md path.",
        "- Write a targeted upstream repair prompt to the semantic_repair_prompt path when the handoff is not semantically sufficient.",
        "",
        "## Source context",
        "",
        f"- semantic_review_mode: {source_index.get('semantic_review_mode', 'required')}",
    ]
    for item in source_index.get("reference_docs", []):
        lines.append(f"- reference_doc: {item.get('abs', '')}")
    if not source_index.get("reference_docs"):
        lines.append("- reference_doc: <none>")

    lines.extend(
        [
            "",
            "## Derived handoff documents",
            "",
            _doc_line("spec"),
            _doc_line("reqs"),
            _doc_line("testplan"),
            _doc_line("baseline_summary"),
            _doc_line("compat_constraints"),
            _doc_line("allowlist"),
            "",
            "## Design assets",
            "",
            f"- rtl_file: {design_assets.get('rtl_file', '') or '<missing>'}",
            f"- rtl_filelist: {design_assets.get('rtl_filelist', '') or '<missing>'}",
            f"- tb_wrapper_file: {design_assets.get('tb_wrapper_file', '') or '<missing>'}",
            f"- tb_py_file: {design_assets.get('tb_py_file', '') or '<missing>'}",
            f"- test_file: {design_assets.get('test_file', '') or '<missing>'}",
            f"- top_level: {design_assets.get('top_level', '') or '<missing>'}",
            f"- test_module: {design_assets.get('test_module', '') or '<missing>'}",
            f"- smoke_testcase: {design_assets.get('smoke_testcase', '') or '<missing>'}",
            "",
            "## Change scope",
            "",
        ]
    )
    for rel_path in allowlist_summary.get("allowed_modify", []):
        lines.append(f"- allowed_modify: {rel_path}")
    for rel_path in allowlist_summary.get("allowed_create", []):
        lines.append(f"- allowed_create: {rel_path}")
    for action in allowlist_summary.get("forbidden_actions", []):
        lines.append(f"- forbidden_action: {action}")
    if not any(
        (
            allowlist_summary.get("allowed_modify"),
            allowlist_summary.get("allowed_create"),
            allowlist_summary.get("forbidden_actions"),
        )
    ):
        lines.append("- <allowlist unavailable>")

    lines.extend(
        [
            "",
            "## Contract audit snapshot",
            "",
            f"- contract_status: {contract_audit.get('status', 'unknown')}",
            f"- inferred_state: {contract_audit.get('inferred_state', 'unknown')}",
            f"- manifest_status: {manifest_validation.get('status', 'missing')}",
            "",
            "Blocking or notable contract findings:",
        ]
    )
    gaps = contract_audit.get("gaps", [])
    if gaps:
        for gap in gaps:
            lines.append(f"- [{gap.get('severity', 'info')}] {gap.get('code', '')}: {gap.get('message', '')}")
            suggestion = str(gap.get("suggestion", "")).strip()
            if suggestion:
                lines.append(f"  Fix hint: {suggestion}")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Review instructions",
            "",
            "Judge the handoff on these dimensions:",
            "1. task alignment with source requirement docs",
            "2. baseline understanding accuracy",
            "3. delta completeness in reqs/delta_spec and testplan",
            "4. compatibility fidelity in compat_constraints and allowlist",
            "5. verification adequacy for the requested change",
            "",
            "The JSON output must use this shape:",
            "",
            "```json",
            "{",
            '  "schema_version": "handoff_semantic_review/v1",',
            '  "status": "pass|needs_repair|skipped",',
            '  "summary": "short overall verdict",',
            '  "scores": {',
            '    "task_alignment": 0,',
            '    "baseline_understanding": 0,',
            '    "delta_completeness": 0,',
            '    "compatibility_fidelity": 0,',
            '    "verification_adequacy": 0',
            "  },",
            '  "findings": [',
            "    {",
            '      "severity": "error|warning|info",',
            '      "code": "short_snake_case_code",',
            '      "message": "concrete finding",',
            '      "evidence_paths": ["path1", "path2"],',
            '      "suggestion": "how the upstream AI should fix it"',
            "    }",
            "  ]",
            "}",
            "```",
            "",
            "Scoring guidance:",
            "- 5 = strong and complete",
            "- 3 = usable but incomplete",
            "- 1 = substantially insufficient",
            "",
            "The markdown review should explain the verdict and reference concrete files.",
            "The semantic repair prompt should be directly copyable by a user and should tell the upstream AI how to revise the handoff bundle without regenerating unrelated files.",
            "",
        ]
    )
    return "\n".join(lines)


def _derive_session_root(
    workspace: Path,
    handoff_root: Path,
    manifest_path: Path | None,
    explicit: Path | None,
) -> Path | None:
    if explicit:
        return explicit.resolve()
    for candidate in filter(None, [manifest_path, handoff_root]):
        inferred = infer_session_root_from_path(candidate, workspace)
        if inferred:
            return inferred.resolve()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventory and validate upstream handoff artifacts")
    ap.add_argument("--handoff-root", default="", help="directory containing raw handoff artifacts")
    ap.add_argument("--manifest", default="", help="optional handoff manifest path")
    ap.add_argument("--workspace", default=".", help="pipeline workspace root")
    ap.add_argument("--target-state", default="", help="required delivery state, default from rules")
    ap.add_argument("--out-dir", default="", help="output directory relative to workspace")
    ap.add_argument("--rules", default="config/handoff_rules.yaml", help="rules file path")
    ap.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA_PATH,
        help="artifact_handoff_manifest schema path used for requirements prompt generation",
    )
    ap.add_argument(
        "--session-root",
        default="",
        help="optional session root for handoff materialization",
    )
    ap.add_argument(
        "--source-requirements-root",
        default="",
        help="optional source_requirements directory for semantic review",
    )
    ap.add_argument(
        "--semantic-review-mode",
        default="",
        help="semantic review mode override: off, auto, or required",
    )
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    search_roots = [Path.cwd().resolve(), workspace, workspace.parent.resolve(), repo_root]
    rules_path = _resolve_input_path(repo_root, args.rules)
    rules = load_rules(rules_path)
    schema_path = _resolve_input_path(repo_root, args.schema)
    schema = load_handoff_schema(schema_path)
    target_state = args.target_state or str(rules.get("target_state_default", "verify_ready"))
    default_out_dir = "artifacts/handoff"
    out_dir = (workspace / (args.out_dir or default_out_dir)).resolve()

    handoff_root_input = args.handoff_root.strip()
    manifest_input = args.manifest.strip()
    if not handoff_root_input and manifest_input:
        manifest_probe = _resolve_existing_path(manifest_input, search_roots)
        handoff_root_input = str(manifest_probe.parent)
    if not handoff_root_input:
        print("[HANDOFF][FAIL] provide --handoff-root or --manifest")
        return 2

    handoff_root = _resolve_existing_path(handoff_root_input, search_roots)
    if not handoff_root.exists() or not handoff_root.is_dir():
        print(f"[HANDOFF][FAIL] handoff root missing or not a directory: {handoff_root}")
        return 2
    handoff_inside_workspace = _is_within(handoff_root, workspace)

    explicit_session_root = _resolve_optional_path(args.session_root, search_roots)

    files = scan_handoff_files(handoff_root)
    inventory_items, buckets = classify_files(files, handoff_root, rules)
    selected = choose_selected_files(buckets, rules)

    manifest_path: Path | None = None
    manifest_data: dict[str, Any] | None = None
    manifest_validation: dict[str, Any] = {"status": "missing", "path": "", "error": ""}
    gaps: list[Gap] = []

    if manifest_input:
        manifest_path = _resolve_existing_path(manifest_input, search_roots)
    elif selected.get("manifest"):
        manifest_path = (handoff_root / selected["manifest"]).resolve()

    if manifest_path:
        manifest_validation["path"] = str(manifest_path)
        try:
            manifest_data, manifest_path = load_handoff_manifest(manifest_path)
            context, manifest_gap = validate_manifest_candidate(
                manifest_data,
                manifest_path,
                workspace,
                target_state,
            )
            if manifest_gap:
                manifest_validation["status"] = "invalid"
                manifest_validation["error"] = manifest_gap.message
                gaps.append(manifest_gap)
            else:
                manifest_validation["status"] = "valid"
                manifest_validation["context_output"] = context.get("output", {})
                docs_section = manifest_data.get("docs", {}) if isinstance(manifest_data, dict) else {}
                if isinstance(docs_section, dict):
                    selected.setdefault("spec", str(docs_section.get("spec_file", "")))
                    selected.setdefault("reqs", str(docs_section.get("reqs_file", "")))
                    selected.setdefault("testplan", str(docs_section.get("testplan_file", "")))
                    selected.setdefault(
                        "baseline_summary", str(docs_section.get("baseline_summary_file", ""))
                    )
                    selected.setdefault(
                        "compat_constraints", str(docs_section.get("compat_constraints_file", ""))
                    )
                    allowlist_doc = docs_section.get("allowlist_file", "")
                    if isinstance(allowlist_doc, str) and allowlist_doc.strip():
                        selected.setdefault("allowlist", allowlist_doc.strip())
        except HandoffError as exc:
            manifest_validation["status"] = "invalid"
            manifest_validation["error"] = str(exc)
            gaps.append(
                Gap(
                    "manifest_invalid",
                    "error",
                    f"provided or discovered handoff manifest is invalid: {exc}",
                    "Regenerate handoff_manifest.json in the artifact_handoff_manifest/v1 format.",
                )
            )
    else:
        gaps.append(
            Gap(
                "manifest_missing",
                "warning",
                "no handoff manifest was provided or discovered",
                "Generate handoff_manifest.json if the handoff is already verify_ready.",
            )
        )
        if not handoff_inside_workspace and not explicit_session_root:
            gaps.append(
                Gap(
                    "handoff_root_outside_workspace",
                    "error",
                    "handoff root is outside the current pipeline workspace and no valid manifest was provided",
                    "Provide --session-root so OpenChipFlow can materialize the bundle into a session workspace, or generate a manifest whose referenced files resolve inside the workspace.",
                )
            )

    session_root = _derive_session_root(workspace, handoff_root, manifest_path, explicit_session_root)
    session_materialization_enabled = session_root is not None
    session_root_rel = _safe_rel(session_root, workspace) if session_root else ""

    handoff_search_roots = [handoff_root] + [root for root in search_roots if root != handoff_root]
    source_index, source_gaps = discover_source_context(
        workspace=workspace,
        handoff_root=handoff_root,
        manifest_data=manifest_data,
        search_roots=handoff_search_roots,
        rules=rules,
        explicit_source_requirements_root=args.source_requirements_root,
        explicit_semantic_review_mode=args.semantic_review_mode,
    )
    gaps.extend(source_gaps)

    gaps.extend(collect_required_doc_gaps(selected, rules, target_state))
    doc_checks, doc_gaps = collect_doc_checks(workspace, handoff_root, selected, rules)
    gaps.extend(doc_gaps)

    allowlist_summary: dict[str, Any] = {
        "path": "",
        "parsed": False,
        "allowed_modify": [],
        "allowed_create": [],
        "forbidden_actions": [],
    }
    if selected.get("allowlist"):
        allowlist_path = (handoff_root / selected["allowlist"]).resolve()
        allowlist_summary, allowlist_gaps = build_allowlist_summary(allowlist_path, handoff_root, workspace)
        gaps.extend(allowlist_gaps)
    design_assets, asset_gaps = infer_design_assets(
        allowlist_summary,
        workspace,
        handoff_root,
        manifest_data=manifest_data,
        materialize_into_session=session_materialization_enabled,
    )
    gaps.extend(asset_gaps)
    gaps.extend(collect_required_asset_gaps(design_assets, rules, target_state))

    case_id = infer_case_id(handoff_root, selected, manifest_data)
    candidate_manifest: dict[str, Any] | None = None
    candidate_manifest_context: dict[str, Any] = {}
    materialized_manifest: dict[str, Any] | None = None
    materialized_manifest_context: dict[str, Any] = {}
    materialization_report: dict[str, Any] = {}
    materialization_output_paths: dict[str, str] = {}
    candidate_manifest_path = out_dir / "handoff_manifest.candidate.json"

    has_materialize_blocker = any(
        gap.severity == "error"
        and (
            gap.code.endswith("_missing")
            or gap.code.endswith("_ambiguous")
            or gap.code in {"allowlist_parse_failed", "manifest_invalid"}
        )
        for gap in gaps
    )
    if session_materialization_enabled and not has_materialize_blocker:
        try:
            materialization_report, materialized_manifest = materialize_handoff_bundle(
                workspace_root=workspace,
                session_root=session_root,
                handoff_root=handoff_root,
                selected=selected,
                allowlist_summary=allowlist_summary,
                design_assets=design_assets,
                manifest_data=manifest_data,
                source_index=source_index,
                case_id=case_id,
                target_state=target_state,
            )
            materialization_output_paths = write_materialization_outputs(
                workspace_root=workspace,
                session_root=session_root,
                report=materialization_report,
                materialized_manifest=materialized_manifest,
            )
            materialized_manifest_context, materialized_gap = validate_manifest_candidate(
                materialized_manifest,
                Path(materialization_output_paths["manifest_path"]),
                workspace,
                target_state,
            )
            if materialized_gap:
                gaps.append(materialized_gap)
                materialized_manifest = None
                materialization_output_paths = {}
                materialization_report = {}
            elif manifest_validation["status"] != "valid":
                candidate_manifest = materialized_manifest
                candidate_manifest_context = materialized_manifest_context
        except Exception as exc:
            gaps.append(
                Gap(
                    "materialization_failed",
                    "error",
                    f"failed to materialize the handoff bundle into the session workspace: {exc}",
                    "Fix the bundle paths so docs/assets are resolvable, then rerun Handoff Intake.",
                )
            )

    if (
        candidate_manifest is None
        and manifest_validation["status"] != "valid"
        and selected.get("spec")
        and selected.get("reqs")
        and selected.get("testplan")
        and not any(gap.severity == "error" and gap.code.endswith("_missing") for gap in gaps)
    ):
        candidate_manifest = build_candidate_manifest(
            case_id,
            workspace,
            handoff_root,
            selected,
            allowlist_summary,
            design_assets,
            source_index,
        )
        candidate_manifest_context, candidate_gap = validate_manifest_candidate(
            candidate_manifest,
            candidate_manifest_path,
            workspace,
            target_state,
        )
        if candidate_gap:
            gaps.append(candidate_gap)
            candidate_manifest = None

    if materialized_manifest is not None:
        relaxed_gaps: list[Gap] = []
        for gap in gaps:
            if gap.code in {"manifest_invalid", "manifest_missing", "candidate_manifest_invalid"}:
                relaxed_gaps.append(
                    Gap(
                        gap.code,
                        "warning",
                        gap.message,
                        "The materialized manifest is available for downstream verify-ready runs; upstream source files can still be cleaned up later.",
                    )
                )
                continue
            relaxed_gaps.append(gap)
        gaps = relaxed_gaps

    gaps = dedupe_gaps(gaps)
    inferred_state = determine_inferred_state(target_state, selected, design_assets, gaps)
    status = "pass" if not any(gap.severity == "error" for gap in gaps) else "needs_repair"

    outputs_cfg = rules.get("outputs", {})
    inventory_path = out_dir / Path(outputs_cfg.get("inventory", "artifacts/handoff/handoff_inventory.json")).name
    audit_path = out_dir / Path(outputs_cfg.get("audit", "artifacts/handoff/handoff_audit.json")).name
    source_index_path = out_dir / Path(outputs_cfg.get("source_index", "artifacts/handoff/handoff_source_index.json")).name
    contract_audit_path = out_dir / Path(outputs_cfg.get("contract_audit", "artifacts/handoff/handoff_contract_audit.json")).name
    gap_report_path = out_dir / Path(outputs_cfg.get("gap_report", "artifacts/handoff/handoff_gap_report.md")).name
    repair_prompt_path = out_dir / Path(outputs_cfg.get("repair_prompt", "artifacts/handoff/handoff_repair_prompt.txt")).name
    contract_repair_prompt_path = out_dir / Path(
        outputs_cfg.get("contract_repair_prompt", "artifacts/handoff/handoff_contract_repair_prompt.txt")
    ).name
    requirements_prompt_path = out_dir / Path(
        outputs_cfg.get("requirements_prompt", "artifacts/handoff/handoff_requirements_prompt.txt")
    ).name
    semantic_review_request_path = out_dir / Path(
        outputs_cfg.get("semantic_review_request", "artifacts/handoff/handoff_semantic_review_request.md")
    ).name
    semantic_review_path = out_dir / Path(
        outputs_cfg.get("semantic_review", "artifacts/handoff/handoff_semantic_review.json")
    ).name
    semantic_review_md_path = out_dir / Path(
        outputs_cfg.get("semantic_review_md", "artifacts/handoff/handoff_semantic_review.md")
    ).name
    semantic_repair_prompt_path = out_dir / Path(
        outputs_cfg.get("semantic_repair_prompt", "artifacts/handoff/handoff_semantic_repair_prompt.txt")
    ).name
    acceptance_path = out_dir / Path(outputs_cfg.get("acceptance", "artifacts/handoff/handoff_acceptance.json")).name
    candidate_manifest_output = (
        out_dir / Path(outputs_cfg.get("candidate_manifest", "artifacts/handoff/handoff_manifest.candidate.json")).name
    )
    materialization_output = (
        out_dir / Path(outputs_cfg.get("materialization", "artifacts/handoff/handoff_materialization.json")).name
    )
    materialized_manifest_output = (
        out_dir / Path(outputs_cfg.get("materialized_manifest", "artifacts/handoff/handoff_manifest.materialized.json")).name
    )

    inventory = {
        "schema_version": "handoff_inventory/v1",
        "generated_at": datetime.now().isoformat(),
        "handoff_root": {"input": handoff_root_input, "abs": str(handoff_root)},
        "files": inventory_items,
        "categories": buckets,
        "selected_files": selected,
        "session_root": session_root_rel,
    }

    requirements_prompt = build_handoff_requirements_prompt(rules, schema, target_state=target_state)
    semantic_review_requested, semantic_review_reason = semantic_review_should_run(
        semantic_review_mode=source_index.get("semantic_review_mode", ""),
        source_index=source_index,
        selected=selected,
    )

    audit = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "target_state": target_state,
        "inferred_state": inferred_state,
        "handoff_root": {
            "input": handoff_root_input,
            "abs": str(handoff_root),
            "inside_workspace": handoff_inside_workspace,
        },
        "workspace": str(workspace),
        "session_root": session_root_rel,
        "session_materialization_enabled": session_materialization_enabled,
        "semantic_review_mode": source_index.get("semantic_review_mode", ""),
        "semantic_review_requested": semantic_review_requested,
        "semantic_review_reason": semantic_review_reason,
        "case_id": case_id,
        "selected_files": selected,
        "inventory_counts": {category: len(paths) for category, paths in buckets.items()},
        "source_index": source_index,
        "manifest_validation": manifest_validation,
        "doc_checks": doc_checks,
        "allowlist": allowlist_summary,
        "design_assets": design_assets,
        "gaps": [gap.as_dict() for gap in gaps],
        "requirements_prompt_available": True,
        "candidate_manifest_available": candidate_manifest is not None,
        "candidate_manifest_context": candidate_manifest_context,
        "materialization_available": bool(materialization_output_paths),
        "materialization_report": materialization_report,
        "materialized_manifest_available": materialized_manifest is not None,
        "materialized_manifest_context": materialized_manifest_context,
        "outputs": {
            "inventory": _safe_rel(inventory_path, workspace),
            "audit": _safe_rel(audit_path, workspace),
            "source_index": _safe_rel(source_index_path, workspace),
            "contract_audit": _safe_rel(contract_audit_path, workspace),
            "gap_report": _safe_rel(gap_report_path, workspace),
            "requirements_prompt": _safe_rel(requirements_prompt_path, workspace),
            "repair_prompt": _safe_rel(repair_prompt_path, workspace),
            "contract_repair_prompt": _safe_rel(contract_repair_prompt_path, workspace),
            "semantic_review_request": _safe_rel(semantic_review_request_path, workspace) if semantic_review_requested else "",
            "semantic_review": _safe_rel(semantic_review_path, workspace),
            "semantic_review_md": _safe_rel(semantic_review_md_path, workspace),
            "semantic_repair_prompt": _safe_rel(semantic_repair_prompt_path, workspace),
            "acceptance": _safe_rel(acceptance_path, workspace),
            "candidate_manifest": _safe_rel(candidate_manifest_output, workspace) if candidate_manifest else "",
            "materialization": materialization_output_paths.get("report_rel", ""),
            "materialized_manifest": materialization_output_paths.get("manifest_rel", ""),
        },
    }

    contract_audit = dict(audit)
    contract_audit["schema_version"] = "handoff_contract_audit/v1"
    contract_audit["contract_status"] = status

    gap_report = build_gap_report(audit)
    repair_prompt = build_repair_prompt(audit)
    semantic_review_request = (
        build_semantic_review_request(
            workspace=workspace,
            handoff_root=handoff_root,
            source_index=source_index,
            selected=selected,
            allowlist_summary=allowlist_summary,
            design_assets=design_assets,
            manifest_validation=manifest_validation,
            contract_audit=contract_audit,
        )
        if semantic_review_requested
        else ""
    )

    write_json(inventory_path, inventory)
    write_json(source_index_path, source_index)
    write_json(audit_path, audit)
    write_json(contract_audit_path, contract_audit)
    write_text(gap_report_path, gap_report + "\n")
    write_text(requirements_prompt_path, requirements_prompt)
    write_text(repair_prompt_path, repair_prompt)
    write_text(contract_repair_prompt_path, repair_prompt)
    if semantic_review_requested:
        write_text(semantic_review_request_path, semantic_review_request + "\n")
    else:
        for stale_path in (
            semantic_review_request_path,
            semantic_review_path,
            semantic_review_md_path,
            semantic_repair_prompt_path,
        ):
            remove_path_if_exists(stale_path)
    if candidate_manifest:
        write_json(candidate_manifest_output, candidate_manifest)
    if materialization_output_paths and materialization_output != Path(materialization_output_paths["report_path"]).resolve():
        write_json(materialization_output, materialization_report)
    if materialization_output_paths and materialized_manifest_output != Path(materialization_output_paths["manifest_path"]).resolve():
        write_json(materialized_manifest_output, materialized_manifest or {})

    if status == "pass":
        print(f"[HANDOFF][OK] intake passed for {handoff_root}")
        print(f"[HANDOFF][OK] audit: {audit_path}")
        print(f"[HANDOFF][OK] contract audit: {contract_audit_path}")
        print(f"[HANDOFF][OK] source index: {source_index_path}")
        print(f"[HANDOFF][OK] requirements prompt: {requirements_prompt_path}")
        if semantic_review_requested:
            print(f"[HANDOFF][OK] semantic review request: {semantic_review_request_path}")
        if candidate_manifest:
            print(f"[HANDOFF][OK] candidate manifest: {candidate_manifest_output}")
        if materialization_output_paths:
            print(f"[HANDOFF][OK] materialization: {materialization_output_paths['report_path']}")
            print(f"[HANDOFF][OK] materialized manifest: {materialization_output_paths['manifest_path']}")
        return 0

    print(f"[HANDOFF][FAIL] intake needs repair for {handoff_root}")
    print(f"[HANDOFF][FAIL] audit: {audit_path}")
    print(f"[HANDOFF][FAIL] contract audit: {contract_audit_path}")
    print(f"[HANDOFF][FAIL] source index: {source_index_path}")
    print(f"[HANDOFF][FAIL] requirements prompt: {requirements_prompt_path}")
    print(f"[HANDOFF][FAIL] repair prompt: {repair_prompt_path}")
    print(f"[HANDOFF][FAIL] contract repair prompt: {contract_repair_prompt_path}")
    if semantic_review_requested:
        print(f"[HANDOFF][FAIL] semantic review request: {semantic_review_request_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RULES_PATH = "config/handoff_rules.yaml"
DEFAULT_SCHEMA_PATH = "cocotb_ex/config/schemas/handoff_manifest.schema.json"


def load_handoff_rules(path: str | Path) -> dict[str, Any]:
    rules_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    rules = raw.get("incremental_handoff")
    if not isinstance(rules, dict):
        raise ValueError(f"missing incremental_handoff rules in {rules_path}")
    return rules


def load_handoff_schema(path: str | Path) -> dict[str, Any]:
    schema_path = Path(path).expanduser().resolve()
    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"handoff schema must be a JSON object: {schema_path}")
    return raw


def _required_doc_filenames() -> list[str]:
    return [
        "source_requirements/ (directory with original requirement/source docs)",
        "baseline_summary.md",
        "compat_constraints.md",
        "changed_files_allowlist.yaml",
        "spec.md",
        "reqs.md or delta_spec.md",
        "testplan.md or testplan_delta.md",
        "handoff_manifest.json when the bundle is verify_ready",
    ]


def _design_layout_lines() -> list[str]:
    return [
        "<handoff_root>/",
        "  source_requirements/",
        "    spec.md",
        "    overview.md",
        "    ...",
        "  baseline_summary.md",
        "  compat_constraints.md",
        "  changed_files_allowlist.yaml",
        "  spec.md",
        "  reqs.md            # or delta_spec.md",
        "  testplan.md        # or testplan_delta.md",
        "  handoff_manifest.json   # required once the bundle is verify_ready",
        "  rtl/...",
        "  filelists/...",
        "  tb/hdl/...",
        "  tb/*.py",
        "  tests/*.py",
    ]


def _schema_required_fields(schema: dict[str, Any], section: str) -> list[str]:
    properties = schema.get("properties", {})
    section_obj = properties.get(section, {})
    if not isinstance(section_obj, dict):
        return []
    fields = section_obj.get("required", [])
    if not isinstance(fields, list):
        return []
    return [str(item).strip() for item in fields if isinstance(item, str) and item.strip()]


def _content_rule_summary(rules: dict[str, Any], key: str) -> str:
    cfg = (rules.get("content_rules") or {}).get(key) or {}
    keywords = [str(item).strip() for item in cfg.get("keywords") or [] if isinstance(item, str) and item.strip()]
    min_hits = int(cfg.get("min_keyword_hits", 1))
    if not keywords:
        return ""
    sample = ", ".join(keywords[:8])
    return f"Include clear headings and at least {min_hits} of the expected concepts: {sample}"


def build_handoff_requirements_prompt(
    rules: dict[str, Any],
    schema: dict[str, Any],
    *,
    target_state: str = "verify_ready",
) -> str:
    required_docs = [str(item).strip() for item in (rules.get("required_docs") or {}).get(target_state, []) if isinstance(item, str)]
    required_assets = [str(item).strip() for item in (rules.get("required_design_assets") or {}).get(target_state, []) if isinstance(item, str)]
    design_fields = _schema_required_fields(schema, "design_assets")
    change_scope_fields = _schema_required_fields(schema, "change_scope")
    verification_fields = _schema_required_fields(schema, "verification")
    source_context_fields = _schema_required_fields(schema, "source_context")
    lines = [
        "You are preparing an incremental OpenChipFlow handoff bundle.",
        "",
        f"Target delivery state: {target_state}",
        "",
        "The bundle must satisfy the OpenChipFlow handoff contract before it is imported.",
        "",
        "Do not regenerate already-correct files. Only add the missing files and missing details.",
        "Do not spread design assets into arbitrary folders. Use the exact relative layout below.",
        "",
        "Required handoff bundle layout:",
        *[f"- {line}" for line in _design_layout_lines()],
        "",
        "Required filenames:",
        *[f"- {name}" for name in _required_doc_filenames()],
        "",
        "Required document categories for verify_ready:",
        *[f"- {name}" for name in required_docs],
        "",
        "Required design assets for verify_ready:",
        *[f"- {name}" for name in required_assets],
        "",
        "Document content requirements:",
        "- source_requirements/: include the original requirement/source documents that the upstream AI used to derive the patch plan. Keep original filenames when possible. This folder is the primary semantic-review anchor.",
        f"- baseline_summary.md: {_content_rule_summary(rules, 'baseline_summary') or 'Describe the baseline design, current behavior, target delta, and impacted interfaces.'}",
        f"- compat_constraints.md: {_content_rule_summary(rules, 'compat_constraints') or 'Describe what must be preserved, what is allowed, and what is forbidden.'}",
        f"- reqs.md / delta_spec.md: {_content_rule_summary(rules, 'reqs') or 'Describe scope, must-have behavior delta, out-of-scope items, and acceptance criteria.'}",
        f"- testplan.md / testplan_delta.md: {_content_rule_summary(rules, 'testplan') or 'List testcase intent, regression scope, and checks.'}",
        "- changed_files_allowlist.yaml must declare allowed_modify, allowed_create, and forbidden_actions.",
        "",
        "Manifest requirements:",
        "- schema_version must be artifact_handoff_manifest/v1",
        "- case_id must be a stable non-empty string",
        f"- delivery_state must be {target_state}",
        f"- docs must include: {', '.join(_schema_required_fields(schema, 'docs'))}",
        f"- design_assets must include: {', '.join(design_fields)}",
        f"- change_scope must include: {', '.join(change_scope_fields)}",
        f"- verification must include: {', '.join(verification_fields)}",
        (
            f"- source_context should include: {', '.join(source_context_fields)}"
            if source_context_fields
            else "- source_context should identify source_requirements/* when semantic review is required."
        ),
        "",
        "Strict path rules:",
        "- RTL files must be under rtl/...",
        "- filelists must be under filelists/...",
        "- SV testbench wrappers must be under tb/hdl/...",
        "- cocotb helper Python files must be under tb/*.py",
        "- cocotb test modules must be under tests/*.py",
        "- original requirement/source documents should stay under source_requirements/...",
        "- changed_files_allowlist.yaml and handoff_manifest.json must use those relative paths consistently.",
        "",
        "Do not leave multiple candidate RTL/TB/test files ambiguous. If more than one candidate exists, handoff_manifest.json must disambiguate them explicitly.",
        "Do not omit the original requirement context. OpenChipFlow semantic review will compare source_requirements/* against the derived reqs/testplan/baseline/compat files.",
        "Do not rename design files unless the manifest and allowlist are updated consistently.",
        "Do not weaken checks by deleting assertions or by broad skip/xfail patterns.",
        "",
        "Output requirement:",
        "Return the finished handoff bundle using the exact file names and directory structure above so OpenChipFlow can import it directly.",
        "",
    ]
    return "\n".join(lines)


def requirements_prompt_from_files(
    *,
    rules_path: str | Path = DEFAULT_RULES_PATH,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    target_state: str = "verify_ready",
) -> str:
    rules = load_handoff_rules(rules_path)
    schema = load_handoff_schema(schema_path)
    return build_handoff_requirements_prompt(rules, schema, target_state=target_state)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


MANIFEST_RE = re.compile(r"^\[MANIFEST\]\s+(.+)$", re.MULTILINE)
QUOTA_SKIP_RE = re.compile(r"^\[INFO\]\s+quota guard skipped for non-AI command: (.+)$", re.MULTILINE)

def run_and_load_manifest(
    project_root: Path,
    request_manifest: Path,
    *,
    dry_run: bool = True,
    skip_quota_guard: bool = True,
) -> tuple[dict, str]:
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "runner.py"),
        "request",
        "--request-manifest",
        str(request_manifest),
    ]
    if dry_run:
        cmd.append("--dry-run")
    env = dict(os.environ)
    if skip_quota_guard:
        env.setdefault("CHIPFLOW_SKIP_QUOTA_GUARD", "1")
    proc = subprocess.run(cmd, cwd=str(project_root), text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise SystemExit(
            f"[FAIL] command failed rc={proc.returncode}\nCMD={' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    match = MANIFEST_RE.search(proc.stdout)
    if not match:
        raise SystemExit(f"[FAIL] missing [MANIFEST] line\nSTDOUT:\n{proc.stdout}")
    manifest_path = Path(match.group(1).strip())
    if not manifest_path.is_file():
        raise SystemExit(f"[FAIL] ui manifest missing: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8")), proc.stdout


def prepare_request_manifest(project_root: Path, template_path: Path, session_id: str) -> Path:
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    payload["session_id"] = session_id
    out_dir = Path(tempfile.mkdtemp(prefix=f"{session_id}_", dir="/tmp"))
    out_path = out_dir / template_path.name
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"[FAIL] {message}")


def require_ui_contract(manifest: dict) -> None:
    require(manifest.get("schema_version") == "runner_ui_manifest/v1", "ui manifest schema_version mismatch")
    require(bool(manifest.get("run_id")), "ui manifest missing run_id")
    require(bool(manifest.get("session_id")), "ui manifest missing session_id")
    require(isinstance(manifest.get("request_artifacts"), list), "ui manifest missing request_artifacts")
    require(isinstance(manifest.get("input_artifacts"), list), "ui manifest missing input_artifacts")
    require(isinstance(manifest.get("primary_artifacts"), list), "ui manifest missing primary_artifacts")
    require(isinstance(manifest.get("secondary_artifacts"), list), "ui manifest missing secondary_artifacts")
    require(isinstance(manifest.get("next_actions"), list), "ui manifest missing next_actions")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test runner request/artifact manifest support")
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    examples = project_root / "artifacts" / "protocol" / "examples"

    spec_request = prepare_request_manifest(project_root, examples / "request_spec_flow.json", "smoke_spec_flow")
    spec_manifest, _ = run_and_load_manifest(project_root, spec_request)
    require_ui_contract(spec_manifest)
    require(spec_manifest["mode"] == "spec_flow", "spec_flow mode missing")
    require(spec_manifest["session_id"] == "smoke_spec_flow", "spec_flow session_id mismatch")
    require(spec_manifest["request_manifest"].endswith("request_spec_flow.json"), "spec_flow request manifest missing")
    require(spec_manifest["dry_run"] is True, "spec_flow should be previewed in smoke")
    require(any(item["id"] == "request_manifest_normalized" and item["exists"] for item in spec_manifest["request_artifacts"]), "spec_flow normalized request missing")
    require(spec_manifest["input_artifacts"], "spec_flow input artifacts missing")
    require(any(item["id"] == "normalized_spec" for item in spec_manifest["primary_artifacts"]), "spec_flow normalized_spec missing")
    require(any(item.get("preview_only") for item in spec_manifest["primary_artifacts"]), "spec_flow preview markers missing")

    intake_request = prepare_request_manifest(project_root, examples / "request_handoff_intake.json", "smoke_handoff_intake")
    intake_manifest, intake_stdout = run_and_load_manifest(
        project_root,
        intake_request,
        dry_run=False,
        skip_quota_guard=False,
    )
    require_ui_contract(intake_manifest)
    require(intake_manifest["mode"] == "handoff_intake", "handoff_intake mode missing")
    require(intake_manifest["session_id"] == "smoke_handoff_intake", "handoff_intake session_id mismatch")
    require(any(item["id"] == "handoff_requirements_prompt" for item in intake_manifest["primary_artifacts"]), "handoff_requirements_prompt missing")
    require(any(item["id"] == "handoff_source_index" for item in intake_manifest["primary_artifacts"]), "handoff_source_index missing")
    require(any(item["id"] == "handoff_audit" for item in intake_manifest["primary_artifacts"]), "handoff_audit missing")
    require(any(item["id"] == "handoff_contract_audit" for item in intake_manifest["primary_artifacts"]), "handoff_contract_audit missing")
    require(any(item["id"] == "handoff_materialized_manifest" for item in intake_manifest["primary_artifacts"]), "handoff_materialized_manifest missing")
    require(any(item["id"] == "handoff_acceptance" for item in intake_manifest["primary_artifacts"]), "handoff_acceptance missing")
    require(intake_manifest["dry_run"] is False, "handoff_intake real run should not be previewed")
    require(not any(item.get("preview_only") for item in intake_manifest["primary_artifacts"]), "handoff_intake real run should not carry preview markers")
    quota_skip_match = QUOTA_SKIP_RE.search(intake_stdout)
    require(quota_skip_match is not None, "handoff_intake should skip quota guard as a host-side workflow")
    require("handoff_intake" in quota_skip_match.group(1), "handoff_intake quota skip reason mismatch")

    verify_request = prepare_request_manifest(
        project_root, examples / "request_incremental_verify_ready.json", "smoke_incremental_verify_ready"
    )
    verify_manifest, _ = run_and_load_manifest(project_root, verify_request)
    require_ui_contract(verify_manifest)
    require(verify_manifest["mode"] == "incremental_verify_ready", "verify_ready mode missing")
    require(verify_manifest["session_id"] == "smoke_incremental_verify_ready", "verify_ready session_id mismatch")
    require(any(item["id"] == "handoff_context" for item in verify_manifest["primary_artifacts"]), "handoff_context missing")
    require(any(item.get("preview_only") for item in verify_manifest["primary_artifacts"]), "verify_ready preview markers missing")

    print("[OK] runner request/artifact manifest smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

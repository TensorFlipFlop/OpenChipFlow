#!/usr/bin/env python3
"""Chip frontend automation runner (opencode-style CLI).

Examples:
  python3 scripts/runner.py list
  python3 scripts/runner.py run plan
  python3 scripts/runner.py run all
  python3 scripts/runner.py stage verify
  python3 scripts/runner.py doctor
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from request_manifest_utils import RequestContext, RequestManifestError, load_request_manifest

DEFAULT_WORKSPACE_HOME = "~/.openchipflow"
REPO_REGISTRY_REL = "workspace/repos.json"

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_STAGE_NOT_FOUND = 3
EXIT_COMMAND_FAIL = 4
EXIT_INTERRUPTED = 130


@dataclass
class CmdResult:
    rc: int
    duration_s: float
    log_file: Path


@dataclass
class RuntimeOverrides:
    model: str | None = None
    variant: str | None = None
    thinking: str | None = None

    def is_empty(self) -> bool:
        return not (self.model or self.variant or self.thinking)


@dataclass
class ExecutionPlan:
    command: str
    target: str | None
    dry_run: bool


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"[ERR] config not found: {path}")
        raise SystemExit(EXIT_CONFIG)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERR] failed to parse config: {path}: {exc}")
        raise SystemExit(EXIT_CONFIG)


def _now_iso() -> str:
    return datetime.now().isoformat()


def workspace_home_path(raw: str | None) -> Path:
    base = raw or os.environ.get("CHIPFLOW_HOME") or DEFAULT_WORKSPACE_HOME
    return Path(base).expanduser().resolve()


def repo_registry_path(workspace_home: Path) -> Path:
    return workspace_home / REPO_REGISTRY_REL


def load_repo_registry(workspace_home: Path) -> dict[str, Any]:
    path = repo_registry_path(workspace_home)
    if not path.exists():
        return {"version": 1, "default_repo": None, "repos": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERR] failed to parse repo registry: {path}: {exc}")
        raise SystemExit(EXIT_CONFIG)

    if not isinstance(data, dict):
        return {"version": 1, "default_repo": None, "repos": {}}
    data.setdefault("version", 1)
    data.setdefault("default_repo", None)
    data.setdefault("repos", {})
    if not isinstance(data["repos"], dict):
        data["repos"] = {}
    return data


def save_repo_registry(workspace_home: Path, data: dict[str, Any]) -> Path:
    path = repo_registry_path(workspace_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def detect_local_project_root(config_rel: str) -> Path:
    cwd = Path.cwd().resolve()
    cfg = Path(config_rel)
    if cfg.is_absolute() and cfg.exists():
        return cfg.parent
    if (cwd / config_rel).exists():
        return cwd
    return Path(__file__).resolve().parents[1]


def resolve_project_root(
    config_rel: str,
    workspace_home: Path,
    repo_name: str | None,
    repo_path: str | None,
) -> tuple[Path, str | None]:
    if repo_path:
        return Path(repo_path).expanduser().resolve(), None

    registry = load_repo_registry(workspace_home)
    repos = registry.get("repos", {})

    if repo_name:
        meta = repos.get(repo_name)
        if not meta:
            print(f"[ERR] repo not found in registry: {repo_name}")
            raise SystemExit(EXIT_CONFIG)
        return Path(meta.get("path", "")).expanduser().resolve(), repo_name

    default_name = registry.get("default_repo")
    if default_name and default_name in repos:
        meta = repos.get(default_name, {})
        return Path(meta.get("path", "")).expanduser().resolve(), default_name

    return detect_local_project_root(config_rel), None


def ensure_project_config(project_root: Path, config_arg: str) -> Path:
    cfg = Path(config_arg)
    config_path = cfg if cfg.is_absolute() else (project_root / cfg)
    config_path = config_path.resolve()
    if not config_path.exists():
        print(f"[ERR] config not found for project root={project_root}: {config_path}")
        print("[HINT] Use '--repo-path <path>' or 'chipflow repo add/use' to select a repo.")
        raise SystemExit(EXIT_CONFIG)
    return config_path


def cmd_repo(args: argparse.Namespace, workspace_home: Path) -> int:
    action = getattr(args, "repo_action", None)
    registry = load_repo_registry(workspace_home)
    repos: dict[str, Any] = registry.setdefault("repos", {})

    if action == "list":
        if not repos:
            print(f"[INFO] no repos registered. registry={repo_registry_path(workspace_home)}")
            return EXIT_OK
        default_name = registry.get("default_repo")
        for name in sorted(repos.keys()):
            meta = repos.get(name, {})
            marker = "*" if name == default_name else " "
            print(f"{marker} {name}\t{meta.get('path', '')}")
        return EXIT_OK

    if action == "init":
        name = args.name.strip()
        path = Path(args.path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)

        cfg_path = path / "config" / "runner.json"
        template_cfg = Path(__file__).resolve().parents[1] / "config" / "runner.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if cfg_path.exists() and not args.force:
            print(f"[ERR] runner config already exists: {cfg_path}")
            print("[HINT] use --force to overwrite existing config.")
            return EXIT_CONFIG
        shutil.copy2(template_cfg, cfg_path)

        guide = path / "README.chipflow.md"
        guide.write_text(
            "# ChipFlow Project Bootstrap\n\n"
            "This repo was initialized by `chipflow repo init`.\n\n"
            "Next steps:\n"
            "1. Edit `config/runner.json` to point to this repo's own workflow commands.\n"
            "2. Add your design/verification sources and scripts.\n"
            "3. Run: `chipflow --repo-path . list` then `chipflow --repo-path . run plan --dry-run`.\n",
            encoding="utf-8",
        )

        if args.git and not (path / ".git").exists():
            subprocess.run(["git", "init"], cwd=str(path), check=False, capture_output=True)

        repos[name] = {"path": str(path), "added_at": _now_iso()}
        if args.set_default or not registry.get("default_repo"):
            registry["default_repo"] = name
        out = save_repo_registry(workspace_home, registry)
        print(f"[OK] repo initialized: {name} -> {path}")
        print(f"[OK] config: {cfg_path}")
        print(f"[OK] registry: {out}")
        return EXIT_OK

    if action == "add":
        name = args.name.strip()
        path = Path(args.path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            print(f"[ERR] repo path not found: {path}")
            return EXIT_CONFIG
        cfg = path / args.config
        if not args.force and not cfg.exists():
            print(f"[ERR] missing runner config in repo: {cfg}")
            print("[HINT] pass --force to register anyway.")
            return EXIT_CONFIG

        repos[name] = {"path": str(path), "added_at": _now_iso()}
        if args.set_default or not registry.get("default_repo"):
            registry["default_repo"] = name
        out = save_repo_registry(workspace_home, registry)
        print(f"[OK] repo added: {name} -> {path}")
        print(f"[OK] registry: {out}")
        return EXIT_OK

    if action == "remove":
        name = args.name.strip()
        if name not in repos:
            print(f"[ERR] repo not found: {name}")
            return EXIT_CONFIG
        repos.pop(name, None)
        if registry.get("default_repo") == name:
            registry["default_repo"] = None
        out = save_repo_registry(workspace_home, registry)
        print(f"[OK] repo removed: {name}")
        print(f"[OK] registry: {out}")
        return EXIT_OK

    if action == "use":
        name = args.name.strip()
        if name not in repos:
            print(f"[ERR] repo not found: {name}")
            return EXIT_CONFIG
        registry["default_repo"] = name
        out = save_repo_registry(workspace_home, registry)
        print(f"[OK] default repo: {name}")
        print(f"[OK] registry: {out}")
        return EXIT_OK

    if action == "current":
        name = registry.get("default_repo")
        if not name:
            print("[INFO] no default repo set")
            return EXIT_OK
        meta = repos.get(name)
        if not meta:
            print(f"[WARN] default repo '{name}' missing from registry")
            return EXIT_OK
        print(f"{name}\t{meta.get('path', '')}")
        return EXIT_OK

    print("[ERR] unknown repo action")
    return EXIT_CONFIG


def emit_event(stream: str, event_type: str, **payload: Any) -> None:
    if stream != "jsonl":
        return
    evt = {"type": event_type, "ts": datetime.now().isoformat(), **payload}
    print(json.dumps(evt, ensure_ascii=False), flush=True)


def _rel_to(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _pipeline_root(project_root: Path) -> Path:
    return (project_root / "cocotb_ex").resolve()


def _pipeline_config(project_root: Path) -> dict[str, Any]:
    cfg = _pipeline_root(project_root) / "ai_cli_pipeline" / "config.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pipeline_global_parameters(project_root: Path) -> dict[str, Any]:
    cfg = _pipeline_config(project_root)
    params = cfg.get("global_parameters") if isinstance(cfg, dict) else {}
    return params if isinstance(params, dict) else {}


def _session_paths(request: RequestContext | None, project_root: Path) -> dict[str, Path]:
    if request is None:
        return {}
    session_root = request.session_root.resolve()
    return {
        "session_root": session_root,
        "handoff_dir": (session_root / "handoff").resolve(),
        "workspace_dir": (session_root / "workspace").resolve(),
        "ops_dir": (session_root / "ops").resolve(),
        "request_dir": request.manifest_path.parent.resolve(),
        "project_root": project_root.resolve(),
    }


def _artifact_entry(
    project_root: Path,
    path: Path,
    *,
    artifact_id: str,
    label: str,
    kind: str = "file",
    preview_only: bool = False,
) -> dict[str, Any]:
    exists = path.exists()
    suffix = path.suffix.lower()
    previewable = suffix in {".md", ".txt", ".json", ".yaml", ".yml", ".log", ".sv", ".py"}
    return {
        "id": artifact_id,
        "label": label,
        "kind": kind,
        "path": _rel_to(project_root, path),
        "abs_path": str(path),
        "exists": exists,
        "previewable": previewable,
        "copyable": True,
        "preview_only": preview_only,
    }


def _infer_mode(request: RequestContext | None, target: str) -> str:
    if request is not None:
        return request.mode
    if target in {"flow:plan", "flow:all"}:
        return "spec_flow"
    if target in {"flow:handoff_intake", "stage:handoff_intake"}:
        return "handoff_intake"
    if target in {"flow:incremental_verify_ready", "stage:incremental_verify_ready"}:
        return "incremental_verify_ready"
    return "generic"


def _collect_primary_artifacts(
    project_root: Path,
    mode: str,
    target: str = "",
    *,
    request: RequestContext | None = None,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    secondary: list[dict[str, Any]] = []
    pipeline_root = _pipeline_root(project_root)
    gp = _pipeline_global_parameters(project_root)
    session_paths = _session_paths(request, project_root)
    handoff_dir = session_paths.get("handoff_dir") or (pipeline_root / "artifacts" / "handoff").resolve()
    session_workspace = session_paths.get("workspace_dir")

    def add(bucket: list[dict[str, Any]], artifact_id: str, label: str, rel_path: str) -> None:
        bucket.append(
            _artifact_entry(
                project_root,
                (pipeline_root / rel_path).resolve(),
                artifact_id=artifact_id,
                label=label,
                preview_only=dry_run,
            )
        )

    if mode == "spec_flow":
        plan_only = target == "flow:plan"
        path_map = [
            ("normalized_spec", "Normalized spec.md", str(gp.get("spec_path") or "ai_cli_pipeline/specs/out/spec.md")),
            ("reqs", "reqs.md", str(gp.get("reqs_path") or "ai_cli_pipeline/specs/out/reqs.md")),
            ("testplan", "testplan.md", str(gp.get("testplan_path") or "ai_cli_pipeline/specs/out/testplan.md")),
        ]
        if not plan_only:
            path_map.extend(
                [
                    ("rtl", "RTL", str(gp.get("rtl_path") or "rtl/ai_dut.sv")),
                    ("rtl_filelist", "RTL filelist", str(gp.get("rtl_filelist_path") or "filelists/ai_dut.f")),
                    ("tb_wrapper", "TB wrapper", str(gp.get("tb_wrapper_path") or "tb/hdl/ai_tb_top.sv")),
                    ("tb_py", "TB python", str(gp.get("tb_py_path") or "tb/ai_tb.py")),
                    ("test_module", "Test module", str(gp.get("test_path") or "tests/test_ai.py")),
                    ("verify_report", "verify.md", "ai_cli_pipeline/verification/verify.md"),
                ]
            )
        for artifact_id, label, rel_path in path_map:
            add(primary, artifact_id, label, rel_path)
        if not plan_only:
            add(secondary, "case_schedule", "case_schedule.json", "artifacts/case_schedule.json")
            add(secondary, "trace_matrix_md", "req_trace_matrix.md", "ai_cli_pipeline/verification/req_trace_matrix.md")
            add(secondary, "trace_matrix_json", "req_trace_matrix.json", "ai_cli_pipeline/verification/req_trace_matrix.json")
        return primary, secondary

    if mode == "handoff_intake":
        for artifact_id, label, path in (
            ("handoff_requirements_prompt", "handoff_requirements_prompt.txt", handoff_dir / "handoff_requirements_prompt.txt"),
            ("handoff_source_index", "handoff_source_index.json", handoff_dir / "handoff_source_index.json"),
            ("handoff_inventory", "handoff_inventory.json", handoff_dir / "handoff_inventory.json"),
            ("handoff_audit", "handoff_audit.json", handoff_dir / "handoff_audit.json"),
            ("handoff_contract_audit", "handoff_contract_audit.json", handoff_dir / "handoff_contract_audit.json"),
            ("handoff_gap_report", "handoff_gap_report.md", handoff_dir / "handoff_gap_report.md"),
            ("handoff_repair_prompt", "handoff_repair_prompt.txt", handoff_dir / "handoff_repair_prompt.txt"),
            ("handoff_contract_repair_prompt", "handoff_contract_repair_prompt.txt", handoff_dir / "handoff_contract_repair_prompt.txt"),
            ("handoff_semantic_review_request", "handoff_semantic_review_request.md", handoff_dir / "handoff_semantic_review_request.md"),
            ("handoff_semantic_review", "handoff_semantic_review.json", handoff_dir / "handoff_semantic_review.json"),
            ("handoff_semantic_review_md", "handoff_semantic_review.md", handoff_dir / "handoff_semantic_review.md"),
            ("handoff_semantic_repair_prompt", "handoff_semantic_repair_prompt.txt", handoff_dir / "handoff_semantic_repair_prompt.txt"),
            ("handoff_acceptance", "handoff_acceptance.json", handoff_dir / "handoff_acceptance.json"),
            ("handoff_candidate_manifest", "handoff_manifest.candidate.json", handoff_dir / "handoff_manifest.candidate.json"),
            ("handoff_materialization", "handoff_materialization.json", handoff_dir / "handoff_materialization.json"),
            ("handoff_materialized_manifest", "handoff_manifest.materialized.json", handoff_dir / "handoff_manifest.materialized.json"),
        ):
            primary.append(_artifact_entry(project_root, path.resolve(), artifact_id=artifact_id, label=label, preview_only=dry_run))
        return primary, secondary

    if mode == "incremental_verify_ready":
        if session_workspace is not None:
            for artifact_id, label, path in (
                ("handoff_context", "handoff_context.json", handoff_dir / "handoff_context.json"),
                ("case_schedule", "case_schedule.json", session_workspace / "artifacts" / "case_schedule.json"),
                ("trace_matrix_md", "req_trace_matrix.md", session_workspace / "ai_cli_pipeline" / "verification" / "req_trace_matrix.md"),
                ("trace_matrix_json", "req_trace_matrix.json", session_workspace / "ai_cli_pipeline" / "verification" / "req_trace_matrix.json"),
                ("verify_report", "verify.md", session_workspace / "ai_cli_pipeline" / "verification" / "verify.md"),
            ):
                primary.append(_artifact_entry(project_root, path.resolve(), artifact_id=artifact_id, label=label, preview_only=dry_run))
        else:
            for artifact_id, label, rel_path in (
                ("handoff_context", "handoff_context.json", str(gp.get("handoff_context_path") or "artifacts/handoff/handoff_context.json")),
                ("case_schedule", "case_schedule.json", str(gp.get("case_schedule_path") or "artifacts/case_schedule.json")),
                ("trace_matrix_md", "req_trace_matrix.md", str(gp.get("trace_matrix_md_path") or "ai_cli_pipeline/verification/req_trace_matrix.md")),
                ("trace_matrix_json", "req_trace_matrix.json", str(gp.get("trace_matrix_json_path") or "ai_cli_pipeline/verification/req_trace_matrix.json")),
                ("verify_report", "verify.md", str(gp.get("verify_report_path") or "ai_cli_pipeline/verification/verify.md")),
            ):
                add(primary, artifact_id, label, rel_path)
        return primary, secondary

    return primary, secondary


def _next_actions(mode: str, primary_artifacts: Iterable[dict[str, Any]], *, dry_run: bool = False) -> list[dict[str, Any]]:
    actions = [{"id": "rerun", "label": "Rerun this request/command"}]
    if mode == "handoff_intake":
        requirements = next((item for item in primary_artifacts if item["id"] == "handoff_requirements_prompt"), None)
        contract_repair = next((item for item in primary_artifacts if item["id"] == "handoff_contract_repair_prompt"), None)
        repair = contract_repair or next((item for item in primary_artifacts if item["id"] == "handoff_repair_prompt"), None)
        semantic_repair = next((item for item in primary_artifacts if item["id"] == "handoff_semantic_repair_prompt"), None)
        materialized = next((item for item in primary_artifacts if item["id"] == "handoff_materialized_manifest"), None)
        candidate = next((item for item in primary_artifacts if item["id"] == "handoff_candidate_manifest"), None)
        for item, action_id, label in (
            (requirements, "copy_requirements_prompt", "Copy requirements prompt"),
            (repair, "copy_contract_repair_prompt", "Copy contract repair prompt"),
            (semantic_repair, "copy_semantic_repair_prompt", "Copy semantic repair prompt"),
        ):
            if item and item.get("exists"):
                actions.append({"id": action_id, "label": label, "artifact": item.get("path")})
        launch_manifest = materialized if materialized and materialized.get("exists") else candidate
        if launch_manifest and launch_manifest.get("exists"):
            actions.append(
                {
                    "id": "launch_verify_ready",
                    "label": "Run verify-ready flow",
                    "handoff_manifest": launch_manifest.get("path"),
                }
            )
    if mode == "spec_flow" and not dry_run:
        actions.append({"id": "launch_all_flow", "label": "Run full spec flow"})
    return actions


def _build_execution_plan(args: argparse.Namespace, request: RequestContext | None) -> ExecutionPlan:
    dry_run = bool(getattr(args, "dry_run", False)) or bool(request.dry_run if request else False)
    if request and args.command == "request":
        return ExecutionPlan(request.execution_command, request.execution_target, dry_run)
    if args.command == "plan":
        return ExecutionPlan("run", "plan", dry_run)
    if args.command == "all":
        return ExecutionPlan("run", "all", dry_run)
    if args.command == "doctor":
        return ExecutionPlan("stage", "precheck", dry_run)
    if args.command == "stage":
        return ExecutionPlan("stage", getattr(args, "name", None), dry_run)
    if args.command == "run":
        return ExecutionPlan("run", getattr(args, "target", None), dry_run)
    return ExecutionPlan(args.command, None, dry_run)


def _merge_runtime(request: RequestContext | None, cli_runtime: RuntimeOverrides) -> RuntimeOverrides:
    if request is None:
        return cli_runtime
    req_runtime = request.runtime
    return RuntimeOverrides(
        model=cli_runtime.model or req_runtime.get("model"),
        variant=cli_runtime.variant or req_runtime.get("variant"),
        thinking=cli_runtime.thinking or req_runtime.get("thinking"),
    )


def apply_runtime_overrides_to_cmd(cmd: str, runtime: RuntimeOverrides) -> str:
    """Append runtime overrides for run_pipeline invocations only."""
    if runtime.is_empty() or "run_pipeline.py" not in cmd:
        return cmd

    parts = [cmd]
    if runtime.model:
        parts.append(f"--model {shlex.quote(runtime.model)}")
    if runtime.variant:
        parts.append(f"--variant {shlex.quote(runtime.variant)}")
    if runtime.thinking:
        parts.append(f"--thinking {shlex.quote(runtime.thinking)}")
    return " ".join(parts)


def apply_request_inputs_to_cmd(cmd: str, request: RequestContext | None) -> str:
    if request is None or "run_pipeline.py" not in cmd:
        return cmd

    parts = [cmd]
    input_flag_map = {
        "spec_source": "--spec-source",
        "handoff_root": "--handoff-root",
        "handoff_manifest": "--handoff-manifest",
        "source_requirements_root": "--source-requirements-root",
    }
    for key, flag in input_flag_map.items():
        value = request.input_path(key)
        if value and flag not in cmd:
            parts.append(f"{flag} {shlex.quote(value)}")
    if request.session_root and "--session-root" not in cmd:
        parts.append(f"--session-root {shlex.quote(str(request.session_root))}")
    scalar_flag_map = {
        "target_state": "--target-state",
        "backend_policy": "--backend-policy",
        "semantic_review_mode": "--semantic-review-mode",
    }
    for key, flag in scalar_flag_map.items():
        value = request.input_params.get(key)
        if isinstance(value, str) and value.strip() and flag not in cmd:
            parts.append(f"{flag} {shlex.quote(value.strip())}")
    return " ".join(parts)


def run_command(
    project_root: Path,
    log_dir: Path,
    stage: str,
    item: dict[str, str],
    dry_run: bool,
    runtime: RuntimeOverrides,
    request: RequestContext | None,
    session_id: str,
    event_stream: str,
) -> CmdResult:
    name = item["name"]
    cmd = apply_request_inputs_to_cmd(apply_runtime_overrides_to_cmd(item["cmd"], runtime), request)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{stage}__{name}__{ts}.log"

    print(f"[RUN] {stage}.{name}: {cmd}")
    print(f"[LOG] {log_file}")
    emit_event(
        event_stream,
        "cmd_started",
        session_id=session_id,
        stage=stage,
        name=name,
        cmd=cmd,
        dry_run=dry_run,
    )
    if dry_run:
        log_file.write_text(f"[DRY-RUN] {cmd}\n", encoding="utf-8")
        emit_event(
            event_stream,
            "cmd_finished",
            session_id=session_id,
            stage=stage,
            name=name,
            rc=0,
            duration_s=0.0,
            dry_run=True,
        )
        return CmdResult(0, 0.0, log_file)

    start = datetime.now()
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
    )

    def _env_int(name: str, default: int, minimum: int = 1) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(minimum, value)

    first_heartbeat_sec = _env_int("CHIPFLOW_STAGE_FIRST_HEARTBEAT_SEC", 60)
    heartbeat_sec = _env_int("CHIPFLOW_STAGE_HEARTBEAT_SEC", 600)
    first_wait = True

    with log_file.open("w", encoding="utf-8") as lf:
        lf.write(f"# stage: {stage}\n# name: {name}\n# cmd: {cmd}\n")
        lf.write("# stream: merged stdout/stderr (live)\n\n## stdout\n")
        lf.flush()

        stream = proc.stdout
        if stream is not None:
            while True:
                wait_interval = first_heartbeat_sec if first_wait else heartbeat_sec
                ready, _, _ = select.select([stream], [], [], wait_interval)
                if ready:
                    line = stream.readline()
                    if line:
                        lf.write(line)
                        lf.flush()
                        print(line, end="")
                        continue

                    if proc.poll() is not None:
                        break
                else:
                    elapsed = int((datetime.now() - start).total_seconds())
                    hb = (
                        f"[WAIT] {stage}.{name}: waiting for command completion "
                        f"(elapsed={elapsed}s, pid={proc.pid})\n"
                    )
                    print(hb, end="")
                    lf.write(hb)
                    lf.flush()
                    first_wait = False

                if proc.poll() is not None:
                    break

            # Drain any trailing buffered output after process exit.
            tail = stream.read()
            if tail:
                lf.write(tail)
                print(tail, end="")

        rc = proc.wait()
        if rc is None:
            rc = 1

        lf.write("\n\n## stderr\n(merged into stdout)\n")
        lf.flush()

    elapsed = (datetime.now() - start).total_seconds()
    with log_file.open("a", encoding="utf-8") as lf:
        lf.write(f"\n# rc: {rc}\n# duration_s: {elapsed:.2f}\n")

    emit_event(
        event_stream,
        "cmd_finished",
        session_id=session_id,
        stage=stage,
        name=name,
        rc=rc,
        duration_s=elapsed,
        dry_run=False,
    )
    return CmdResult(rc, elapsed, log_file)


def execute_stage(
    cfg: dict[str, Any],
    stage_name: str,
    project_root: Path,
    run_id: str,
    dry_run: bool,
    runtime: RuntimeOverrides,
    request: RequestContext | None,
    session_id: str,
    event_stream: str,
) -> int:
    stages = cfg.get("stages", {})
    if stage_name not in stages:
        print(f"[ERR] stage not found: {stage_name}")
        return EXIT_STAGE_NOT_FOUND

    stage = stages[stage_name]
    stage_log_dir = project_root / cfg.get("log_root", ".runner_logs") / run_id
    stage_log_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Stage: {stage_name} ===")
    print(stage.get("description", ""))
    emit_event(event_stream, "stage_started", run_id=run_id, session_id=session_id, stage=stage_name)

    for item in stage.get("commands", []):
        result = run_command(project_root, stage_log_dir, stage_name, item, dry_run, runtime, request, session_id, event_stream)
        if result.rc != 0:
            print(f"[ERR] command failed rc={result.rc}: {stage_name}.{item['name']}")
            emit_event(event_stream, "stage_finished", run_id=run_id, session_id=session_id, stage=stage_name, rc=EXIT_COMMAND_FAIL)
            return EXIT_COMMAND_FAIL
    emit_event(event_stream, "stage_finished", run_id=run_id, session_id=session_id, stage=stage_name, rc=EXIT_OK)
    return EXIT_OK


def execute_flow(
    cfg: dict[str, Any],
    flow_name: str,
    project_root: Path,
    run_id: str,
    dry_run: bool,
    runtime: RuntimeOverrides,
    request: RequestContext | None,
    session_id: str,
    event_stream: str,
) -> int:
    flows = cfg.get("flows", {})
    flow = flows.get(flow_name)
    if flow is None:
        print(f"[ERR] flow not found: {flow_name}")
        return EXIT_CONFIG

    for stage_name in flow:
        rc = execute_stage(cfg, stage_name, project_root, run_id, dry_run, runtime, request, session_id, event_stream)
        if rc != EXIT_OK:
            return rc

    print(f"\n[OK] flow={flow_name} finished. logs under {cfg.get('log_root', '.runner_logs')}/{run_id}")
    return EXIT_OK


def print_inventory(cfg: dict[str, Any]) -> None:
    print("Flows:")
    for k, v in cfg.get("flows", {}).items():
        print(f"- {k}: {' -> '.join(v)}")
    print("\nStages:")
    for k, v in cfg.get("stages", {}).items():
        print(f"- {k}: {v.get('description', '')}")


def write_run_manifest(
    project_root: Path,
    run_id: str,
    command: str,
    target: str,
    dry_run: bool,
    runtime: RuntimeOverrides,
    rc: int,
    session_id: str,
    request: RequestContext | None = None,
    config_path: Path | None = None,
    repo_name: str | None = None,
) -> Path:
    logs_root = project_root / ".runner_logs" / run_id
    log_files: list[str] = []
    if logs_root.exists():
        log_files = sorted(str(p.relative_to(project_root)) for p in logs_root.glob("*.log"))

    out_dir = project_root / "artifacts" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ui_manifest.json"

    mode = _infer_mode(request, target)
    primary_artifacts, secondary_artifacts = _collect_primary_artifacts(
        project_root,
        mode,
        target,
        request=request,
        dry_run=dry_run,
    )
    request_artifacts: list[dict[str, Any]] = []
    input_artifacts: list[dict[str, Any]] = []
    if request is not None:
        request_artifacts.append(
            _artifact_entry(
                project_root,
                request.manifest_path,
                artifact_id="request_manifest",
                label="request manifest",
            )
        )
        normalized = request.session_root / "request.normalized.json"
        request_artifacts.append(
            _artifact_entry(
                project_root,
                normalized,
                artifact_id="request_manifest_normalized",
                label="request.normalized.json",
            )
        )
        input_artifacts = [
            {
                **item.as_dict(project_root),
                "id": name,
                "label": name,
            }
            for name, item in sorted(request.inputs.items())
        ]

    payload = {
        "schema_version": "runner_ui_manifest/v1",
        "run_id": run_id,
        "session_id": session_id,
        "generated_at": datetime.now().isoformat(),
        "command": command,
        "target": target,
        "mode": mode,
        "dry_run": dry_run,
        "project_root": str(project_root),
        "repo_name": repo_name,
        "config_path": str(config_path) if config_path else None,
        "runtime": {
            "model": runtime.model,
            "variant": runtime.variant,
            "thinking": runtime.thinking,
        },
        "rc": rc,
        "log_files": log_files,
        "request_manifest": str(request.manifest_path) if request else None,
        "request_artifacts": request_artifacts,
        "input_artifacts": input_artifacts,
        "primary_artifacts": primary_artifacts,
        "secondary_artifacts": secondary_artifacts,
        "next_actions": _next_actions(mode, primary_artifacts, dry_run=dry_run),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def run_quota_guard(project_root: Path, min_left_percent: float = 5.0) -> int:
    if os.environ.get("CHIPFLOW_SKIP_QUOTA_GUARD") == "1":
        print("[WARN] quota guard skipped via CHIPFLOW_SKIP_QUOTA_GUARD=1")
        return EXIT_OK

    guard_script = project_root / "tools" / "pre_task_quota_guard.py"
    if not guard_script.exists():
        print(f"[ERR] quota guard script missing: {guard_script}")
        return EXIT_COMMAND_FAIL

    max_age_sec = os.environ.get("CHIPFLOW_QUOTA_MAX_AGE_SEC", "600")
    refresh_timeout_sec = os.environ.get("CHIPFLOW_QUOTA_REFRESH_TIMEOUT_SEC", "90")

    cmd = [
        sys.executable,
        str(guard_script),
        "--min-left",
        str(min_left_percent),
        "--max-age-sec",
        str(max_age_sec),
        "--refresh-timeout-sec",
        str(refresh_timeout_sec),
    ]

    gemini_text = os.environ.get("CHIPFLOW_GEMINI_STATUS_TEXT")
    if gemini_text:
        cmd.extend(["--gemini-status-text", gemini_text])

    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out:
        print(out)
    if err:
        print(err)

    if proc.returncode == 0:
        print("[QUOTA] guard pass (5h + Week >= threshold)")
        return EXIT_OK

    if proc.returncode == 2:
        print("[BLOCK] quota too low in 5h/Week window (<5%), task refused.")
        return EXIT_COMMAND_FAIL

    combined = "\n".join(x for x in (out, err) if x).lower()
    if "quota snapshot remains stale after refresh" in combined:
        print("[ERR] quota snapshot is stale; refresh did not produce a fresh Codex usage event.")
        print("[HINT] Retry after a fresh codex interaction, or use CHIPFLOW_SKIP_QUOTA_GUARD=1 only for non-AI diagnosis.")
        return EXIT_COMMAND_FAIL

    print("[ERR] quota guard unavailable, task refused for safety.")
    return EXIT_COMMAND_FAIL


def describe_execution(plan: ExecutionPlan) -> str:
    target = (plan.target or "").strip()
    if not target:
        return plan.command
    return f"{plan.command} {target}".strip()


def is_non_ai_command(plan: ExecutionPlan) -> tuple[bool, str]:
    if plan.dry_run:
        return True, f"{describe_execution(plan)} --dry-run"
    if plan.command == "stage" and plan.target == "handoff_intake":
        return True, "stage handoff_intake (host-side intake/audit only)"
    if plan.command == "run" and plan.target == "handoff_intake":
        return True, "run handoff_intake (host-side intake/audit only)"
    if plan.command == "stage" and plan.target == "precheck":
        return True, "stage precheck"
    if plan.command == "run" and plan.target == "precheck":
        return True, "run precheck"
    return False, ""


def normalize_legacy_args(argv: list[str]) -> list[str]:
    """Backward compatibility for old flag style (--mode ...)."""
    if "--mode" not in argv and "--list" not in argv:
        return argv

    if "--list" in argv:
        new_argv = [a for a in argv if a != "--list"]
        return ["list", *new_argv]

    new_argv = argv[:]
    mode_idx = new_argv.index("--mode")
    if mode_idx + 1 >= len(new_argv):
        return new_argv

    mode = new_argv[mode_idx + 1]
    # remove --mode <x>
    del new_argv[mode_idx: mode_idx + 2]

    if mode in ("plan", "all"):
        return [mode, *new_argv]

    if mode == "stage":
        stage_name = None
        if "--stage" in new_argv:
            sidx = new_argv.index("--stage")
            if sidx + 1 < len(new_argv):
                stage_name = new_argv[sidx + 1]
            del new_argv[sidx: sidx + 2]
        if stage_name:
            return ["stage", stage_name, *new_argv]
        return ["stage", *new_argv]

    return [mode, *new_argv]


def add_runtime_override_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default=None, help="runtime model override for AI CLIs")
    p.add_argument("--variant", default=None, help="runtime variant override for AI CLIs")
    p.add_argument("--thinking", default=None, help="runtime thinking override for AI CLIs")


def add_event_stream_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--event-stream", choices=["off", "jsonl"], default="off", help="emit structured event stream")


def add_request_manifest_arg(p: argparse.ArgumentParser, required: bool = False) -> None:
    p.add_argument(
        "--request-manifest",
        required=required,
        default=None,
        help="path to runner request manifest JSON",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chip frontend automation runner (opencode-style command mode)"
    )
    parser.add_argument("--config", default="config/runner.json", help="runner config path")
    parser.add_argument("--workspace-home", default=None, help="workspace home (default: ~/.openchipflow or $CHIPFLOW_HOME)")
    parser.add_argument("--repo", default=None, help="registered repo name")
    parser.add_argument("--repo-path", default=None, help="direct repo path (overrides --repo)")

    sub = parser.add_subparsers(dest="command")

    list_p = sub.add_parser("list", help="list available flows and stages")
    list_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(list_p)

    plan_p = sub.add_parser("plan", help="run planning flow without implementation")
    plan_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(plan_p)
    add_request_manifest_arg(plan_p)
    add_runtime_override_args(plan_p)

    all_p = sub.add_parser("all", help="run full flow")
    all_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(all_p)
    add_request_manifest_arg(all_p)
    add_runtime_override_args(all_p)

    doctor_p = sub.add_parser("doctor", help="run precheck stage only")
    doctor_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(doctor_p)
    add_request_manifest_arg(doctor_p)
    add_runtime_override_args(doctor_p)

    run_p = sub.add_parser("run", help="run a flow/stage by name (flow first, then stage)")
    run_p.add_argument("target", help="flow or stage name, e.g. plan/all/verify")
    run_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(run_p)
    add_request_manifest_arg(run_p)
    add_runtime_override_args(run_p)

    stage_p = sub.add_parser("stage", help="run one stage explicitly")
    stage_p.add_argument("name", help="stage name")
    stage_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(stage_p)
    add_request_manifest_arg(stage_p)
    add_runtime_override_args(stage_p)

    request_p = sub.add_parser("request", help="execute a mode-specific request manifest")
    request_p.add_argument("--dry-run", action="store_true", help="print and log commands only")
    add_event_stream_arg(request_p)
    add_request_manifest_arg(request_p, required=True)
    add_runtime_override_args(request_p)

    repo_p = sub.add_parser("repo", help="manage workspace repo registry")
    repo_sub = repo_p.add_subparsers(dest="repo_action")

    repo_list = repo_sub.add_parser("list", help="list registered repos")
    _ = repo_list

    repo_add = repo_sub.add_parser("add", help="add repo to workspace registry")
    repo_add.add_argument("name", help="repo alias")
    repo_add.add_argument("path", help="repo absolute/relative path")
    repo_add.add_argument("--set-default", action="store_true", help="set this repo as default")
    repo_add.add_argument("--force", action="store_true", help="allow missing runner config")
    repo_add.add_argument("--config", default="config/runner.json", help="config path to validate within repo")

    repo_init = repo_sub.add_parser("init", help="create a minimal chipflow-ready repo skeleton and register it")
    repo_init.add_argument("name", help="repo alias")
    repo_init.add_argument("path", help="target directory")
    repo_init.add_argument("--set-default", action="store_true", help="set this repo as default")
    repo_init.add_argument("--force", action="store_true", help="overwrite existing config/runner.json")
    repo_init.add_argument("--git", action="store_true", help="initialize git repo if missing")

    repo_remove = repo_sub.add_parser("remove", help="remove repo from registry")
    repo_remove.add_argument("name", help="repo alias")

    repo_use = repo_sub.add_parser("use", help="set default repo")
    repo_use.add_argument("name", help="repo alias")

    repo_sub.add_parser("current", help="show default repo")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    argv = normalize_legacy_args(argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_CONFIG

    workspace_home = workspace_home_path(getattr(args, "workspace_home", None))

    if args.command == "repo":
        return cmd_repo(args, workspace_home)

    project_root, repo_name = resolve_project_root(
        config_rel=args.config,
        workspace_home=workspace_home,
        repo_name=getattr(args, "repo", None),
        repo_path=getattr(args, "repo_path", None),
    )
    config_path = ensure_project_config(project_root, args.config)
    cfg = load_config(config_path)

    request: RequestContext | None = None
    request_manifest_arg = getattr(args, "request_manifest", None)
    if request_manifest_arg:
        try:
            request = load_request_manifest(request_manifest_arg, project_root)
        except RequestManifestError as exc:
            print(f"[ERR] {exc}")
            return EXIT_CONFIG
        print(f"[REQUEST] manifest={request.manifest_path}")
        print(f"[REQUEST] session_id={request.session_id} mode={request.mode}")

    if args.command == "list":
        print(f"[PROJECT] root={project_root}")
        if repo_name:
            print(f"[PROJECT] repo={repo_name}")
        print_inventory(cfg)
        return EXIT_OK

    cli_runtime = RuntimeOverrides(
        model=getattr(args, "model", None),
        variant=getattr(args, "variant", None),
        thinking=getattr(args, "thinking", None),
    )
    runtime = _merge_runtime(request, cli_runtime)
    plan = _build_execution_plan(args, request)
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    session_id = request.session_id if request else datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")

    if not runtime.is_empty():
        print(
            "[RUNTIME] overrides: "
            f"model={runtime.model or '-'} "
            f"variant={runtime.variant or '-'} "
            f"thinking={runtime.thinking or '-'}"
        )

    skip_guard, reason = is_non_ai_command(plan)
    if skip_guard:
        print(f"[INFO] quota guard skipped for non-AI command: {reason}")
    else:
        guard_rc = run_quota_guard(project_root)
        if guard_rc != EXIT_OK:
            return guard_rc

    target_label = args.command
    rc = EXIT_CONFIG

    emit_event(
        args.event_stream,
        "run_started",
        run_id=run_id,
        session_id=session_id,
        command=args.command,
        effective_command=plan.command,
        target=plan.target,
        dry_run=plan.dry_run,
        mode=request.mode if request else None,
    )

    if plan.command == "run":
        target = plan.target or ""
        if target in cfg.get("flows", {}):
            target_label = f"flow:{target}"
            rc = execute_flow(cfg, target, project_root, run_id, plan.dry_run, runtime, request, session_id, args.event_stream)
        else:
            target_label = f"stage:{target}"
            rc = execute_stage(cfg, target, project_root, run_id, plan.dry_run, runtime, request, session_id, args.event_stream)
    elif plan.command == "stage":
        stage_name = plan.target or ""
        target_label = f"stage:{stage_name}"
        rc = execute_stage(cfg, stage_name, project_root, run_id, plan.dry_run, runtime, request, session_id, args.event_stream)
    else:
        print(f"[ERR] unsupported execution command: {plan.command}")
        rc = EXIT_CONFIG

    emit_event(args.event_stream, "run_finished", run_id=run_id, session_id=session_id, target=target_label, rc=rc)

    manifest = write_run_manifest(
        project_root=project_root,
        run_id=run_id,
        command=args.command,
        target=target_label,
        dry_run=plan.dry_run,
        runtime=runtime,
        rc=rc,
        session_id=session_id,
        request=request,
        config_path=config_path,
        repo_name=repo_name,
    )
    print(f"[MANIFEST] {manifest}")
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(EXIT_INTERRUPTED)

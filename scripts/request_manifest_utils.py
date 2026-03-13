#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "runner_request_manifest/v1"
SUPPORTED_MODES = {"spec_flow", "handoff_intake", "incremental_verify_ready"}
PATH_INPUT_KEYS = (
    "spec_source",
    "handoff_root",
    "handoff_manifest",
    "source_requirements_root",
)


class RequestManifestError(RuntimeError):
    pass


@dataclass
class ResolvedInput:
    name: str
    kind: str
    import_mode: str
    original_path: Path | None
    resolved_path: Path
    source_type: str

    def as_dict(self, project_root: Path) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "kind": self.kind,
            "import_mode": self.import_mode,
            "source_type": self.source_type,
            "resolved_path": str(self.resolved_path),
            "exists": self.resolved_path.exists(),
        }
        if self.original_path:
            payload["original_path"] = str(self.original_path)
        try:
            payload["resolved_rel"] = str(self.resolved_path.relative_to(project_root))
        except ValueError:
            payload["resolved_rel"] = str(self.resolved_path)
        return payload


@dataclass
class RequestContext:
    manifest_path: Path
    session_id: str
    session_root: Path
    mode: str
    execution_command: str
    execution_target: str
    dry_run: bool
    runtime: dict[str, Any]
    inputs: dict[str, ResolvedInput]
    input_params: dict[str, Any]
    raw: dict[str, Any]

    def input_path(self, name: str) -> str:
        item = self.inputs.get(name)
        return str(item.resolved_path) if item else ""

    def to_normalized_dict(self, project_root: Path) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "manifest_path": str(self.manifest_path),
            "session_id": self.session_id,
            "session_root": str(self.session_root),
            "mode": self.mode,
            "execution": {
                "command": self.execution_command,
                "target": self.execution_target,
                "dry_run": self.dry_run,
            },
            "runtime": self.runtime,
            "inputs": {name: item.as_dict(project_root) for name, item in sorted(self.inputs.items())},
            "input_params": self.input_params,
        }


def _session_id(raw: str | None) -> str:
    if raw and raw.strip():
        return raw.strip()
    return datetime.now().strftime("session_%Y%m%d_%H%M%S_%f")


def _extract_session_id_from_path(path: Path, project_root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return None
    parts = rel.parts
    for idx in range(len(parts) - 2):
        if parts[idx : idx + 2] == ("cocotb_ex", "artifacts") and idx + 3 < len(parts) and parts[idx + 2] == "sessions":
            return parts[idx + 3]
        if parts[idx : idx + 2] == ("artifacts", "sessions") and idx + 2 < len(parts):
            return parts[idx + 2]
    return None


def _infer_session_id(raw_inputs: dict[str, Any], project_root: Path, manifest_dir: Path) -> str | None:
    for key in ("handoff_manifest", "handoff_root", "spec_source", "source_requirements_root"):
        raw = raw_inputs.get(key)
        if isinstance(raw, str):
            path_value = raw
        elif isinstance(raw, dict):
            path_value = raw.get("path")
            if not isinstance(path_value, str):
                continue
        else:
            continue
        try:
            resolved = _resolve_path(path_value, project_root, manifest_dir)
        except Exception:
            continue
        session_id = _extract_session_id_from_path(resolved, project_root)
        if session_id:
            return session_id
    return None


def _ensure_dict(name: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise RequestManifestError(f"'{name}' must be a JSON object")


def _resolve_path(raw_path: str, project_root: Path, manifest_dir: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    manifest_candidate = (manifest_dir / candidate).resolve()
    if manifest_candidate.exists():
        return manifest_candidate
    return (project_root / candidate).resolve()


def _snapshot_path(src: Path, dst_root: Path, project_root: Path) -> Path:
    dst_root.mkdir(parents=True, exist_ok=True)
    try:
        rel = src.relative_to(project_root)
        dst = dst_root / rel
    except ValueError:
        dst = dst_root / src.name
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def _resolve_input_entry(
    name: str,
    raw: Any,
    *,
    project_root: Path,
    manifest_dir: Path,
    session_root: Path,
) -> ResolvedInput | None:
    if raw in (None, "", {}):
        return None

    if isinstance(raw, str):
        entry = {"path": raw}
    elif isinstance(raw, dict):
        entry = dict(raw)
    else:
        raise RequestManifestError(f"input '{name}' must be a string or object")

    import_mode = str(entry.get("import_mode") or "reference").strip().lower()
    if import_mode not in {"reference", "snapshot"}:
        raise RequestManifestError(f"input '{name}' import_mode must be 'reference' or 'snapshot'")

    default_kind = "directory" if name in {"handoff_root", "source_requirements_root"} else "file"
    kind = str(entry.get("kind") or default_kind).strip().lower()
    content = entry.get("content")
    filename = str(entry.get("filename") or ("spec.md" if name == "spec_source" else f"{name}.txt")).strip()

    if isinstance(content, str):
        dst_dir = session_root / "inputs" / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / filename
        dst.write_text(content, encoding="utf-8")
        return ResolvedInput(
            name=name,
            kind="file",
            import_mode="snapshot",
            original_path=None,
            resolved_path=dst,
            source_type="inline_text",
        )

    raw_path = entry.get("path")
    if not raw_path:
        raise RequestManifestError(f"input '{name}' requires 'path' or 'content'")

    src = _resolve_path(str(raw_path), project_root=project_root, manifest_dir=manifest_dir)
    if not src.exists():
        raise RequestManifestError(f"input '{name}' path does not exist: {src}")

    if kind == "directory" and not src.is_dir():
        raise RequestManifestError(f"input '{name}' expected a directory: {src}")
    if kind == "file" and not src.is_file():
        raise RequestManifestError(f"input '{name}' expected a file: {src}")

    resolved = src
    if import_mode == "snapshot":
        resolved = _snapshot_path(src, session_root / "inputs" / name, project_root)

    return ResolvedInput(
        name=name,
        kind=kind,
        import_mode=import_mode,
        original_path=src,
        resolved_path=resolved,
        source_type="path",
    )


def _resolve_execution(mode: str, execution_cfg: dict[str, Any]) -> tuple[str, str, bool]:
    command = str(execution_cfg.get("command") or "run").strip()
    target = str(execution_cfg.get("target") or "").strip()
    dry_run = bool(execution_cfg.get("dry_run", False))

    if mode == "spec_flow":
        phase = str(execution_cfg.get("mode") or target or "all").strip().lower()
        if phase not in {"plan", "all"}:
            raise RequestManifestError("spec_flow execution.mode must be 'plan' or 'all'")
        return "run", phase, dry_run
    if mode == "handoff_intake":
        return "run", "handoff_intake", dry_run
    if mode == "incremental_verify_ready":
        return "run", "incremental_verify_ready", dry_run
    raise RequestManifestError(f"unsupported mode: {mode}")


def load_request_manifest(path: str | Path, project_root: Path) -> RequestContext:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.exists():
        raise RequestManifestError(f"request manifest not found: {manifest_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RequestManifestError(f"failed to parse request manifest: {manifest_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise RequestManifestError("request manifest root must be a JSON object")
    schema_version = str(raw.get("schema_version") or "").strip()
    if schema_version != SCHEMA_VERSION:
        raise RequestManifestError(
            f"request manifest schema_version must be '{SCHEMA_VERSION}', got: {schema_version or '<missing>'}"
        )

    mode = str(raw.get("mode") or "").strip()
    if mode not in SUPPORTED_MODES:
        raise RequestManifestError(
            f"request manifest mode must be one of {sorted(SUPPORTED_MODES)}"
        )

    inferred_session_id = _infer_session_id(_ensure_dict("inputs", raw.get("inputs", {})), project_root, manifest_path.parent)
    session_id = _session_id(raw.get("session_id") or inferred_session_id)
    pipeline_root = (project_root / "cocotb_ex").resolve()
    session_base = (
        pipeline_root / "artifacts" / "sessions"
        if pipeline_root.exists()
        else project_root / "artifacts" / "sessions"
    )
    session_root = (session_base / session_id).resolve()
    session_root.mkdir(parents=True, exist_ok=True)

    execution_cfg = _ensure_dict("execution", raw.get("execution", {}))
    command, target, dry_run = _resolve_execution(mode, execution_cfg)

    runtime_cfg = _ensure_dict("runtime", raw.get("runtime", {}))
    inputs_cfg = _ensure_dict("inputs", raw.get("inputs", {}))

    manifest_dir = manifest_path.parent
    inputs: dict[str, ResolvedInput] = {}
    for key in PATH_INPUT_KEYS:
        item = _resolve_input_entry(
            key,
            inputs_cfg.get(key),
            project_root=project_root,
            manifest_dir=manifest_dir,
            session_root=session_root,
        )
        if item:
            inputs[key] = item

    input_params = {
        key: value
        for key, value in inputs_cfg.items()
        if key not in PATH_INPUT_KEYS and value not in (None, "", {})
    }

    context = RequestContext(
        manifest_path=manifest_path,
        session_id=session_id,
        session_root=session_root,
        mode=mode,
        execution_command=command,
        execution_target=target,
        dry_run=dry_run,
        runtime=runtime_cfg,
        inputs=inputs,
        input_params=input_params,
        raw=raw,
    )

    normalized_path = session_root / "request.normalized.json"
    normalized_path.write_text(
        json.dumps(context.to_normalized_dict(project_root), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return context

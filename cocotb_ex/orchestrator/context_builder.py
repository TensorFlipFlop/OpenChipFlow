import base64
import fnmatch
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REQ_RE = re.compile(r"\bREQ[_-][A-Za-z0-9_.-]+\b")


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha(path: Path) -> str:
    output = _run_git(["hash-object", str(path)])
    return output.strip()


def load_policies(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PyYAML required to read {path}: {exc}") from exc
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def classify_kind(path: str, policies: dict) -> str:
    if path.startswith("cocotb_ex/rtl/"):
        return "DUT"
    if path.startswith("cocotb_ex/tests/"):
        return "CASE"
    for level in policies.get("tb_levels", []):
        name = level.get("name", "")
        for pattern in level.get("patterns", []) or []:
            if fnmatch.fnmatch(path, pattern):
                return name
    if path.startswith("cocotb_ex/tb/"):
        return "TB2"
    return "CONFIG"


def req_ids_from_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return sorted(set(REQ_RE.findall(text)))


def repo_state() -> dict:
    head = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["branch", "--show-current"])
    dirty = bool(_run_git(["status", "--porcelain"]))
    return {"head_commit": head, "branch": branch, "dirty": dirty}


def collect_code_snapshot(paths: list[str], policies: dict) -> list[dict]:
    snapshot = []
    for path in paths:
        file_path = Path(path)
        if not file_path.exists():
            continue
        excerpt = "\n".join(file_path.read_text(encoding="utf-8", errors="replace").splitlines()[:60])
        snapshot.append(
            {
                "path": path,
                "kind": classify_kind(path, policies),
                "git_blob_sha1": git_blob_sha(file_path),
                "sha256": sha256_file(file_path),
                "excerpt": excerpt,
            }
        )
    return snapshot


def build_cleanroom_packet(
    case_id: str,
    job_id: str,
    spec_ir_path: Path,
    reqs_path: Path | None,
    error_summary: dict,
    repro_cmd: str,
    repro_params: dict,
    taboo_list: list[str],
    policies_path: Path,
    output_path: Path,
) -> dict:
    policies = load_policies(policies_path)
    spec_sha = sha256_file(spec_ir_path)
    req_ids = req_ids_from_file(reqs_path) if reqs_path else []

    diff_paths = _run_git(["diff", "--name-only"]).splitlines()
    staged_diff = _run_git(["diff", "--cached"])
    staged_diff_b64 = base64.b64encode(staged_diff.encode("utf-8")).decode("ascii")

    packet = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "job_id": job_id,
        "spec": {
            "spec_ir_path": str(spec_ir_path),
            "spec_ir_sha256": spec_sha,
            "req_ids": req_ids,
            "excerpt": spec_ir_path.read_text(encoding="utf-8", errors="replace")[:4000],
        },
        "repo_state": repo_state(),
        "code_snapshot": {
            "files": collect_code_snapshot(diff_paths, policies),
            "staged_diff_unified_b64": staged_diff_b64,
        },
        "error_summary": error_summary,
        "repro": {"cmd": repro_cmd, "case_params": repro_params},
        "taboo_list": taboo_list,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return packet

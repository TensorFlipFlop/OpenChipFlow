import base64
import fnmatch
import hashlib
import hmac
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


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


def _load_permit_key(key_file: Path) -> str:
    key = None
    if "PERMIT_HMAC_KEY" in os.environ:
        key = os.environ["PERMIT_HMAC_KEY"]
    if not key and key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("Missing PERMIT_HMAC_KEY and permit key file not found.")
    return key


def _staged_blob_sha(path: str) -> str:
    output = _run_git(["ls-files", "-s", "--", path])
    parts = output.split()
    return parts[1] if len(parts) >= 2 else ""


def _staged_sha256(path: str) -> str:
    content = _run_git(["show", f":{path}"]).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def collect_staged_tb3_files(tb3_patterns: list[str]) -> list[str]:
    files = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]).splitlines()
    matched = []
    for f in files:
        for pat in tb3_patterns:
            if fnmatch.fnmatch(f, pat):
                matched.append(f)
                break
    return matched


def generate_permit(
    case_id: str,
    tb3_paths: list[str],
    permit_dir: Path,
    key_file: Path,
    referee_model: str = "Referee",
    required_regression: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> Path:
    if not tb3_paths:
        raise RuntimeError("No TB-3 paths provided for permit generation.")

    base_commit = _run_git(["rev-parse", "HEAD"])
    permit_id = f"PERMIT_{case_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    payload = {
        "version": 1,
        "permit_id": permit_id,
        "case_id": case_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "issuer_role": "Referee",
        "referee_model": referee_model,
        "base_commit": base_commit,
        "allow_tb3_change": True,
        "tb3_bindings": [],
        "forbidden": forbidden or ["no_unapproved_tb3_change"],
        "required_regression": required_regression or [],
    }

    for path in tb3_paths:
        payload["tb3_bindings"].append(
            {
                "path": path,
                "sha256": _staged_sha256(path),
                "git_blob_sha1": _staged_blob_sha(path),
            }
        )

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    key = _load_permit_key(key_file)
    signature = hmac.new(key.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()

    permit_dir.mkdir(parents=True, exist_ok=True)
    permit_path = permit_dir / f"{case_id}.permit.yaml"
    permit_path.write_text(
        "\n".join(
            [
                "sig_alg: HMAC-SHA256",
                f"payload_b64: {payload_b64}",
                f"signature_hex: {signature}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return permit_path


def write_regression_ok(path: Path, permit_id: str, base_commit: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"permit_id: {permit_id}",
                f"base_commit: {base_commit}",
                "",
            ]
        ),
        encoding="utf-8",
    )

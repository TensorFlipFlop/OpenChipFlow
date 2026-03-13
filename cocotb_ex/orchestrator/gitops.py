import subprocess
from pathlib import Path


def write_current_case(path: Path, case_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case_id.strip() + "\n", encoding="utf-8")


def write_current_permit_id(path: Path, permit_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(permit_id.strip() + "\n", encoding="utf-8")


def git_commit(message: str, paths: list[str] | None = None, allow_empty: bool = False) -> None:
    if paths:
        subprocess.run(["git", "add", *paths], check=True)
    else:
        subprocess.run(["git", "add", "-A"], check=True)

    cmd = ["git", "commit", "-m", message]
    if allow_empty:
        cmd.append("--allow-empty")
    subprocess.run(cmd, check=True)

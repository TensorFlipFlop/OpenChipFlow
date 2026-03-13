import subprocess
from typing import Sequence


def run_command(cmd: Sequence[str], env: dict | None = None) -> int:
    result = subprocess.run(cmd, check=False, text=True, env=env)
    return result.returncode


def run_sequence(commands: list[Sequence[str]], env: dict | None = None) -> bool:
    for cmd in commands:
        if run_command(cmd, env=env) != 0:
            return False
    return True

import os
import shlex
import subprocess
from typing import Sequence


def run_fix_command(cmd: Sequence[str], extra_env: dict | None = None) -> bool:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(cmd, check=False, text=True, env=env)
    return result.returncode == 0


def parse_cmd(cmd_str: str) -> list[str]:
    return shlex.split(cmd_str)

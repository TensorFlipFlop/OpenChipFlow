#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib import error, request

_BAD_MARKERS = (
    "授权错误",
    "unauthorized",
    "not login",
    "not logged",
    "auth failed",
    "invalid token",
)
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub("", text)


def _read_token_from_config(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip() in ("access_token", "token"):
                token = value.strip().strip('"').strip("'")
                if token:
                    return token
    except Exception:
        return ""
    return ""


def read_gitee_token(config_path: str | None = None) -> str:
    path = Path(config_path).expanduser() if config_path else Path.home() / ".gitee" / "config.yml"
    return _read_token_from_config(path)


def probe_gitee_user_api(token: str, timeout_sec: int = 5, user_agent: str = "openchipflow/1.0") -> tuple[bool, str]:
    if not token:
        return False, "missing token in ~/.gitee/config.yml"

    req = request.Request(
        "https://gitee.com/api/v5/user",
        headers={
            "Authorization": f"token {token}",
            "User-Agent": user_agent,
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            status = getattr(resp, "status", resp.getcode())
            if status == 200:
                return True, "api /user 200"
            return False, f"api /user status={status}"
    except error.HTTPError as exc:
        return False, f"api /user status={exc.code}"
    except Exception as exc:
        return False, f"api probe failed: {exc}"


def check_gitee_auth(
    cli_timeout_sec: int = 8,
    api_timeout_sec: int = 5,
    user_agent: str = "openchipflow/1.0",
) -> dict:
    result = {
        "ok": False,
        "method": "none",
        "detail": "",
        "status_rc": -1,
        "status_tail": "",
        "api_detail": "",
    }

    if not shutil.which("gitee"):
        result["detail"] = "gitee CLI not found"
        return result

    result["method"] = "gitee auth status"
    status_output = ""
    try:
        status = subprocess.run(
            ["gitee", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=cli_timeout_sec,
        )
        result["status_rc"] = status.returncode
        status_output = "\n".join(x for x in (status.stdout, status.stderr) if x)
    except Exception as exc:
        status_output = str(exc)

    clean = _strip_ansi(status_output).lower()
    result["status_tail"] = (status_output.strip().splitlines()[-1:] or [""])[0]
    if result["status_rc"] == 0 and not any(marker in clean for marker in _BAD_MARKERS):
        result["ok"] = True
        result["method"] = "gitee auth status"
        result["detail"] = "authenticated via `gitee auth status`"
        return result

    token = read_gitee_token()
    api_ok, api_detail = probe_gitee_user_api(token, timeout_sec=api_timeout_sec, user_agent=user_agent)
    result["api_detail"] = api_detail
    if api_ok:
        result["ok"] = True
        result["method"] = "gitee api /user"
        result["detail"] = f"authenticated via gitee API ({api_detail})"
        return result

    status_detail = result["status_tail"] or f"gitee auth status exit={result['status_rc']}"
    result["detail"] = f"{status_detail}; fallback={api_detail}"
    return result

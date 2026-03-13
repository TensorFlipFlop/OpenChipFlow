#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Add tools directory to path for ToolRegistry import
_TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

_REPO_TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
if _REPO_TOOLS_DIR not in sys.path:
    sys.path.insert(0, _REPO_TOOLS_DIR)

try:
    from registry import ToolRegistry
except ImportError:
    # Fallback if running from a different context
    print(f"[WARN] Could not import ToolRegistry from {_TOOLS_DIR}")
    ToolRegistry = None

try:
    from gitee_auth import check_gitee_auth
except ImportError:
    def check_gitee_auth(*_args, **_kwargs):
        return {
            "ok": False,
            "method": "none",
            "detail": "failed to import gitee_auth helper",
            "status_rc": -1,
            "status_tail": "",
            "api_detail": "",
        }

try:
    from handoff_utils import HandoffError, build_handoff_context, load_handoff_manifest
except ImportError:
    HandoffError = ValueError

    def load_handoff_manifest(*_args, **_kwargs):
        raise HandoffError("failed to import handoff_utils.load_handoff_manifest")

    def build_handoff_context(*_args, **_kwargs):
        raise HandoffError("failed to import handoff_utils.build_handoff_context")


_AUTH_FAILURE_PATTERNS = [
    re.compile(r"authorization code is required", re.IGNORECASE),
    re.compile(r"enter the authorization code", re.IGNORECASE),
    re.compile(r"please visit the following url to authorize", re.IGNORECASE),
    re.compile(r"failed to authenticate", re.IGNORECASE),
    re.compile(r"authenticate with user code", re.IGNORECASE),
    re.compile(r"oauth", re.IGNORECASE),
    re.compile(r"not logged in", re.IGNORECASE),
    re.compile(r"login required", re.IGNORECASE),
    re.compile(r"you must be logged in", re.IGNORECASE),
    re.compile(r"please run .* login", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"invalid api key", re.IGNORECASE),
    re.compile(r"missing api key", re.IGNORECASE),
    re.compile(r"api key (is )?not set", re.IGNORECASE),
    re.compile(r"no api key", re.IGNORECASE),
    re.compile(r"authentication failed", re.IGNORECASE),
    re.compile(r"status code 401", re.IGNORECASE),
    re.compile(r"status code 403", re.IGNORECASE),
]
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_LOG_ERROR_RE = re.compile(r"error", re.IGNORECASE)
_LOG_EXCERPT_TAIL_LINES = 100
_LOG_EXCERPT_ERROR_CONTEXT = 10


def _env_int(name, default, minimum=1):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    return value


def _strip_ansi(text):
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub("", text)


def _find_ai_cli_name(cmd):
    for item in cmd:
        base = os.path.basename(item)
        if base in ("claude", "codex", "gemini", "opencode"):
            return base
    return ""


def _current_git_branch(workspace):
    try:
        probe = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    if probe.returncode != 0:
        return ""
    return (probe.stdout or "").strip()


def _detect_auth_failure(stdout, stderr):
    combined = "\n".join(part for part in (stdout, stderr) if part)
    cleaned = _strip_ansi(combined)
    if not cleaned:
        return False, ""
    for pattern in _AUTH_FAILURE_PATTERNS:
        if pattern.search(cleaned):
            for line in cleaned.splitlines():
                if pattern.search(line):
                    trimmed = line.strip()
                    if "http://" in trimmed or "https://" in trimmed:
                        return True, "OAuth login prompt"
                    if len(trimmed) > 120:
                        return True, f"{trimmed[:117]}..."
                    return True, trimmed
            return True, "authentication required"
    return False, ""


_AUTH_CACHE_HINTS = {
    "gemini": {
        "paths": ["~/.gemini", "~/.config/gemini", "~/.config/gemini-cli"],
        "files": ["oauth_creds.json", "mcp-oauth-tokens-v2.json", "google_accounts.json"],
    },
    "claude": {
        "paths": ["~/.claude", "~/.claude.json", "~/.config/claude"],
        "files": [".credentials.json", "auth.json"],
    },
    "codex": {
        "paths": ["~/.codex", "~/.config/openai"],
        "files": ["auth.json"],
    },
    "opencode": {
        "paths": ["~/.opencode", "~/.config/opencode", "~/.local/share/opencode"],
        "files": ["credentials.json", "auth.json", "antigravity-accounts.json"],
    },
}
_EXPECTED_DOCKER_CONFIG_MOUNTS = {
    "claude": "~/.config/claude",
    "codex": "~/.config/openai",
    "opencode": "~/.opencode",
}
_TOOL_NETWORK_PROBES = {
    "codex": [("chatgpt.com", 443)],
    "gemini": [("generativelanguage.googleapis.com", 443)],
    "claude": [("api.anthropic.com", 443)],
}
_PROXY_ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
_NETWORK_FAILURE_PATTERNS = [
    re.compile(r"stream disconnected before completion", re.IGNORECASE),
    re.compile(r"error sending request for url", re.IGNORECASE),
    re.compile(r"transport channel closed", re.IGNORECASE),
    re.compile(r"operation not permitted", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution", re.IGNORECASE),
    re.compile(r"connection (timed out|refused|reset)", re.IGNORECASE),
]


def _path_has_content(path):
    if os.path.isdir(path):
        try:
            return any(os.scandir(path))
        except OSError:
            return False
    if os.path.isfile(path):
        return os.path.getsize(path) > 0
    return False


def _probe_tcp(host, port=443, timeout_sec=3):
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True, f"{host}:{port}"
    except OSError as exc:
        return False, f"{host}:{port} ({exc})"


def _collect_proxy_endpoints():
    endpoints = []
    seen = set()
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if not value:
            continue
        parsed = urlparse(value)
        scheme = (parsed.scheme or "").lower()
        host = parsed.hostname
        port = parsed.port
        if not host:
            continue
        if port is None:
            if scheme == "https":
                port = 443
            elif scheme in ("socks5", "socks5h", "socks4", "socks4a"):
                port = 1080
            else:
                port = 80
        key_id = (scheme, host, int(port))
        if key_id in seen:
            continue
        seen.add(key_id)
        endpoints.append((scheme, host, int(port), key))
    return endpoints


def _probe_http_proxy_connect(proxy_host, proxy_port, target_host, target_port=443, timeout_sec=3):
    try:
        with socket.create_connection((proxy_host, proxy_port), timeout=timeout_sec) as sock:
            connect_req = (
                f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                f"Host: {target_host}:{target_port}\r\n"
                "Proxy-Connection: keep-alive\r\n\r\n"
            )
            sock.sendall(connect_req.encode("ascii", errors="ignore"))
            sock.settimeout(timeout_sec)
            data = sock.recv(1024)
            if not data:
                return False, f"{proxy_host}:{proxy_port} (empty CONNECT response)"
            first_line = data.decode("iso-8859-1", errors="replace").splitlines()[0].strip()
            m = re.match(r"^HTTP/\d\.\d\s+(\d{3})", first_line)
            if m and m.group(1).startswith("2"):
                return True, f"{proxy_host}:{proxy_port} CONNECT {target_host}:{target_port}"
            return False, f"{proxy_host}:{proxy_port} CONNECT {target_host}:{target_port} ({first_line})"
    except OSError as exc:
        return False, f"{proxy_host}:{proxy_port} CONNECT {target_host}:{target_port} ({exc})"


def _check_proxy_network(timeout_sec=3, target_host=None, target_port=443):
    endpoints = _collect_proxy_endpoints()
    if not endpoints:
        return None, "no proxy configured"

    errors = []
    for scheme, host, port, env_key in endpoints:
        if target_host and scheme in ("http", "https", ""):
            ok, detail = _probe_http_proxy_connect(
                host, port, target_host, target_port=target_port, timeout_sec=timeout_sec
            )
        else:
            ok, detail = _probe_tcp(host, port=port, timeout_sec=timeout_sec)
        if ok:
            return True, f"{env_key} -> {detail}"
        errors.append(f"{env_key} -> {detail}")
    return False, "; ".join(errors)


def _check_tool_network(cli_name, timeout_sec=3):
    probes = _TOOL_NETWORK_PROBES.get(cli_name, [])
    probe_host, probe_port = probes[0] if probes else (None, 443)

    proxy_ok, proxy_detail = _check_proxy_network(
        timeout_sec=timeout_sec,
        target_host=probe_host,
        target_port=probe_port,
    )
    if proxy_ok is True:
        return True, f"proxy e2e ok ({proxy_detail})"
    if proxy_ok is False:
        return False, f"proxy configured but e2e failed ({proxy_detail})"

    if not probes:
        return True, "no probe configured"

    errors = []
    for host, port in probes:
        ok, detail = _probe_tcp(host, port=port, timeout_sec=timeout_sec)
        if ok:
            return True, detail
        errors.append(detail)
    return False, "; ".join(errors)


def _detect_network_failure(stdout, stderr):
    combined = "\n".join(part for part in (stdout, stderr) if part)
    cleaned = _strip_ansi(combined)
    if not cleaned:
        return False, ""

    for pattern in _NETWORK_FAILURE_PATTERNS:
        if pattern.search(cleaned):
            for line in cleaned.splitlines():
                if pattern.search(line):
                    text = line.strip()
                    if len(text) > 160:
                        text = text[:157] + "..."
                    return True, text
            return True, "network unavailable"
    return False, ""


def _auth_cache_present(cli_name, base_dir):
    hints = _AUTH_CACHE_HINTS.get(cli_name, {})
    paths = hints.get("paths", [])
    files = hints.get("files", [])
    for raw_path in paths:
        resolved = expand_path(raw_path, base_dir)
        if os.path.isfile(resolved):
            if os.path.getsize(resolved) > 0:
                return True, raw_path
            continue
        if os.path.isdir(resolved):
            if not files and _path_has_content(resolved):
                return True, raw_path
            for name in files:
                candidate = os.path.join(resolved, name)
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    return True, f"{raw_path}/{name}"
    return False, ""


def _check_auth(cli_name, tool, base_dir):
    env_vars = tool.get("env", [])
    for var in env_vars:
        if os.environ.get(var):
            return True, f"{var} set"
    cache_ok, cache_detail = _auth_cache_present(cli_name, base_dir)
    if cache_ok:
        return True, f"cache {cache_detail}"
    env_hint = ", ".join(env_vars) if env_vars else "API key"
    return False, f"missing {env_hint} and auth cache"


def _collect_used_tools(config, role_filter=None):
    roles = config.get("roles", {})
    tools = config.get("ai_cli_tools", {})
    order = config.get("execution_order", [])
    if role_filter:
        order = [name for name in order if name in role_filter]
    used = {}
    for role_name in order:
        role = roles.get(role_name)
        if not role:
            continue
        if not role_filter and role.get("enabled", True) is False:
            continue
        tool_name = role.get("ai_cli")
        if tool_name in tools:
            used[tool_name] = tools[tool_name]
    return used


def _collect_write_required_roles(config):
    """Return roles that must run with writable tool permissions."""
    groups = config.get("role_groups", {})
    target_groups = config.get("writable_role_groups", ["fixer", "reviewer"])
    required = set()
    for group in target_groups:
        for role_name in groups.get(group, []):
            required.add(role_name)
    return required


def _tool_write_capability(tool):
    """Best-effort write-capability check for an AI tool config."""
    cmd = tool.get("cmd") or []
    runner = tool.get("runner", "host")
    cli = _find_ai_cli_name(cmd)

    joined = " ".join(cmd).lower()
    if "read-only" in joined or "readonly" in joined:
        return False, "explicit read-only mode"

    if cli == "codex":
        sandbox = ""
        for idx, tok in enumerate(cmd):
            if tok == "--sandbox" and idx + 1 < len(cmd):
                sandbox = str(cmd[idx + 1]).strip().lower()
                break
        if sandbox in ("workspace-write", "danger-full-access"):
            return True, f"codex sandbox={sandbox}"
        if sandbox:
            return False, f"codex sandbox={sandbox}"
        return False, "codex sandbox not explicitly writable"

    if runner == "docker":
        return True, "docker workspace mount is rw"

    return True, "host mode assumed writable"


def _extract_last_diff_block(text):
    matches = re.findall(r"```diff\n(.*?)```", text, flags=re.S)
    if not matches:
        return ""
    return matches[-1].strip() + "\n"


def _extract_diff_paths(diff_text):
    paths = set()
    for line in diff_text.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line.strip())
        if not m:
            continue
        paths.add(m.group(1).strip())
        paths.add(m.group(2).strip())
    return paths


def _allowed_patch_paths_for_role(role):
    params = role.get("parameters", {}) if isinstance(role, dict) else {}
    allow_keys = {
        "dut_file",
        "tb_file",
        "tb_py_file",
        "test_file",
        "filelist_file",
        "fix_notes",
        "summary_file",
    }
    allowed = set()
    for key in allow_keys:
        value = params.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        norm = os.path.normpath(value).replace("\\", "/")
        if norm.startswith("../") or os.path.isabs(norm):
            continue
        allowed.add(norm)
    return allowed


def _git_has_changes(workspace):
    try:
        res = subprocess.run(
            ["git", "-C", workspace, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    return bool((res.stdout or "").strip())


def _auto_apply_patch_from_log(fixer_name, fixer_role, log_dir, workspace):
    """Apply last ```diff``` block from fixer log when fixer could not write files."""
    log_path = os.path.join(log_dir, f"{fixer_name}.log")
    if not os.path.exists(log_path):
        return False

    try:
        text = open(log_path, "r", encoding="utf-8", errors="replace").read()
    except Exception as exc:
        print(f"[WARN] {fixer_name}: failed to read fixer log for patch apply: {exc}")
        return False

    diff_text = _extract_last_diff_block(text)
    if not diff_text:
        return False

    changed_paths = _extract_diff_paths(diff_text)
    allowed_paths = _allowed_patch_paths_for_role(fixer_role)
    if changed_paths and allowed_paths and not changed_paths.issubset(allowed_paths):
        extra = sorted(changed_paths - allowed_paths)
        print(f"[WARN] {fixer_name}: skip auto-apply, patch touches disallowed paths: {extra}")
        return False

    patch_file = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".diff", encoding="utf-8") as tmp:
            tmp.write(diff_text)
            patch_file = tmp.name

        check = subprocess.run(
            ["git", "-C", workspace, "apply", "--check", patch_file],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check.returncode != 0:
            err = (check.stderr or "").strip()
            print(f"[WARN] {fixer_name}: git apply --check failed: {err}")
            return False

        apply_res = subprocess.run(
            ["git", "-C", workspace, "apply", patch_file],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if apply_res.returncode != 0:
            err = (apply_res.stderr or "").strip()
            print(f"[WARN] {fixer_name}: git apply failed: {err}")
            return False

        print(f"[INFO] {fixer_name}: auto-applied patch from fixer log")
        return True
    except Exception as exc:
        print(f"[WARN] {fixer_name}: auto-apply patch failed: {exc}")
        return False
    finally:
        if patch_file and os.path.exists(patch_file):
            try:
                os.remove(patch_file)
            except OSError:
                pass


def _docker_mounts_include(tool, expected_source, base_dir):
    expected = expand_path(expected_source, base_dir)
    for mount in tool.get("mounts", []):
        source = mount.get("source")
        if not source:
            continue
        if expand_path(source, base_dir) == expected:
            return True
    return False


def _check_gitee_auth_status():
    auth = check_gitee_auth(
        cli_timeout_sec=8,
        api_timeout_sec=5,
        user_agent="openchipflow-run-pipeline/1.0",
    )
    return bool(auth.get("ok", False)), str(auth.get("detail", "gitee auth check failed"))


def preflight_check(config, base_dir, role_filter=None, check_all_tools=False):
    print("=== Pipeline Preflight ===")
    if check_all_tools:
        used_tools = dict(config.get("ai_cli_tools", {}))
    else:
        used_tools = _collect_used_tools(config, role_filter=role_filter)
    ai_tools = {name: tool for name, tool in used_tools.items() if _find_ai_cli_name(tool.get("cmd", []))}
    if not ai_tools:
        print("[WARN] No AI tools found for preflight.")
        return True

    ok = True
    if any(tool.get("runner") == "docker" for tool in ai_tools.values()):
        if not shutil.which("docker"):
            print("[FAIL] docker: not found (required for docker-based tools)")
            ok = False
        else:
            try:
                probe = subprocess.run(
                    ["docker", "info"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if probe.returncode != 0:
                    detail = (probe.stderr or probe.stdout or "docker daemon unavailable").strip().splitlines()[0]
                    print(f"[FAIL] docker: daemon access check failed ({detail})")
                    ok = False
            except Exception as exc:
                print(f"[FAIL] docker: daemon access check failed ({exc})")
                ok = False

    seen = set()
    for tool in ai_tools.values():
        cli_name = _find_ai_cli_name(tool.get("cmd", []))
        runner = tool.get("runner", "host")
        key = (cli_name, runner)
        if key in seen:
            continue
        seen.add(key)
        label = f"{cli_name} ({runner})"
        if runner == "host" and not shutil.which(cli_name):
            print(f"[FAIL] {label}: CLI not found in PATH")
            ok = False
            continue
        if runner == "docker":
            expected_mount = _EXPECTED_DOCKER_CONFIG_MOUNTS.get(cli_name)
            if expected_mount and not _docker_mounts_include(tool, expected_mount, base_dir):
                print(f"[FAIL] {label}: missing docker mount for {expected_mount}")
                ok = False
        auth_ok, detail = _check_auth(cli_name, tool, base_dir)
        if auth_ok:
            print(f"[OK] {label}: auth detected ({detail})")
        else:
            print(f"[FAIL] {label}: auth not detected ({detail})")
            ok = False

        net_ok, net_detail = _check_tool_network(cli_name, timeout_sec=3)
        if net_ok:
            print(f"[OK] {label}: network probe ({net_detail})")
        else:
            print(f"[FAIL] {label}: network probe failed ({net_detail})")
            print("       [FIX] Ensure outbound HTTPS is allowed for AI CLI endpoints.")
            print("       [FIX] OpenChipFlow depends on live LLM calls and requires network access.")
            ok = False

    # Writable enforcement for fixer/reviewer roles
    required_roles = _collect_write_required_roles(config)
    roles = config.get("roles", {})
    tools_map = config.get("ai_cli_tools", {})
    for role_name in sorted(required_roles):
        if role_filter and role_name not in role_filter:
            continue
        role = roles.get(role_name)
        if not role:
            continue
        if role.get("enabled", True) is False:
            continue
        tool_name = role.get("ai_cli")
        tool_cfg = tools_map.get(tool_name)
        if not tool_cfg:
            print(f"[FAIL] writable-check {role_name}: tool '{tool_name}' not found")
            ok = False
            continue
        writable, reason = _tool_write_capability(tool_cfg)
        if writable:
            print(f"[OK] writable-check {role_name}: {tool_name} ({reason})")
        else:
            print(f"[FAIL] writable-check {role_name}: {tool_name} ({reason})")
            ok = False

    if ok:
        print("[OK] Preflight checks passed.")
    else:
        print("[FAIL] Preflight checks failed.")
    return ok

def deep_merge(base, override):
    """Recursively merge override into base."""
    for key, value in override.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    local_path = path.replace("config.json", "config.local.json")
    if os.path.exists(local_path):
        print(f"[INFO] Loading local override: {local_path}")
        with open(local_path, "r", encoding="utf-8") as f:
            local_config = json.load(f)
            deep_merge(config, local_config)
            
    apply_tool_assignments(config)
    return config


def apply_tool_assignments(config, explicit_overrides=None):
    """Apply tool assignments from role_groups and tool_assignments.
    
    Args:
        config: The merged configuration dict.
        explicit_overrides: Set of role names that have explicit ai_cli overrides
                           from local config (these will NOT be overwritten).
    """
    groups = config.get("role_groups", {})
    assignments = config.get("tool_assignments", {})
    roles = config.get("roles", {})
    explicit_overrides = explicit_overrides or set()

    for group_name, tool_name in assignments.items():
        if group_name not in groups:
            print(f"[WARN] Tool assignment for unknown group '{group_name}' ignored.")
            continue
        
        for role_name in groups[group_name]:
            if role_name in roles:
                # Skip if role has explicit ai_cli override from local config
                if role_name in explicit_overrides:
                    continue
                roles[role_name]["ai_cli"] = tool_name


def _load_capability_matrix(base_dir, workspace=None, explicit_path=None):
    candidates = []
    if explicit_path:
        candidates.append(expand_path(explicit_path, base_dir))
    if workspace:
        candidates.append(os.path.join(workspace, "artifacts/capabilities/capabilities.json"))

    cur = base_dir
    for _ in range(4):
        candidates.append(os.path.join(cur, "artifacts/capabilities/capabilities.json"))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
        except Exception:
            continue
    return {}, ""


def _upsert_cli_flag(cmd, aliases, value, prefer=None):
    if not value:
        return cmd, False

    out = list(cmd)
    for i, tok in enumerate(out):
        if tok in aliases and i + 1 < len(out):
            out[i + 1] = value
            return out, True

    flag = prefer or aliases[0]
    insert_at = len(out)
    # Keep stdin '-' sentinel at the end if present
    if out and out[-1] == "-":
        insert_at -= 1

    out[insert_at:insert_at] = [flag, value]
    return out, True


def _upsert_codex_config(cmd, key, value):
    if not key or value is None:
        return cmd, False

    rendered = f'{key}="{value}"'
    out = list(cmd)
    idx = 0
    while idx < len(out) - 1:
        if out[idx] == "-c":
            raw = out[idx + 1]
            if isinstance(raw, str) and raw.startswith(f"{key}="):
                out[idx + 1] = rendered
                return out, True
            idx += 2
            continue
        idx += 1

    insert_at = len(out)
    if out and out[-1] == "-":
        insert_at -= 1
    out[insert_at:insert_at] = ["-c", rendered]
    return out, True


def _runtime_model_profiles(caps):
    if not isinstance(caps, dict):
        return {}
    catalog = caps.get("runtime_catalog") or {}
    profiles = catalog.get("model_profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def _runtime_model_family(model, model_profiles):
    if not model:
        return ""
    prof = model_profiles.get(model)
    if isinstance(prof, dict):
        return str(prof.get("family") or "").strip()
    return ""


def apply_runtime_ai_cli_overrides(config, model=None, variant=None, thinking=None, capability_path=None, workspace=None, base_dir=None):
    if not (model or variant or thinking):
        return

    caps, caps_path = _load_capability_matrix(base_dir or "", workspace=workspace, explicit_path=capability_path)
    tool_caps = (caps.get("tools") or {}) if isinstance(caps, dict) else {}
    model_profiles = _runtime_model_profiles(caps)
    selected_family = _runtime_model_family(model, model_profiles)

    if caps_path:
        print(f"[INFO] Runtime capability matrix: {caps_path}")
    else:
        print("[WARN] capability matrix not found; runtime overrides apply best-effort")

    known_tool_bases = {"codex", "gemini", "opencode"}

    for tool_name, tool_cfg in config.get("ai_cli_tools", {}).items():
        cmd = tool_cfg.get("cmd") or []
        if not cmd:
            continue

        base = os.path.basename(cmd[0])
        if base not in known_tool_bases:
            continue

        cap = tool_caps.get(base, {}) if isinstance(tool_caps, dict) else {}
        supports = (cap.get("capabilities") or {}) if isinstance(cap, dict) else {}

        has_cap = bool(cap)
        changed = False

        if model:
            model_supported = supports.get("model_switch", False) if has_cap else True
            if selected_family and base != selected_family:
                model_supported = False
            if model_supported:
                cmd, ok = _upsert_cli_flag(cmd, ("--model", "-m"), model, prefer="--model")
                changed = changed or ok

        if variant:
            if base == "codex" and selected_family == "codex":
                cmd, ok = _upsert_codex_config(cmd, "model_reasoning_effort", variant)
                changed = changed or ok
            else:
                variant_supported = supports.get("variant_switch", False) if has_cap else False
                if selected_family and base != selected_family:
                    variant_supported = False
                if variant_supported:
                    cmd, ok = _upsert_cli_flag(cmd, ("--variant",), variant)
                    changed = changed or ok

        if thinking:
            thinking_supported = supports.get("thinking_switch", False) if has_cap else False
            if selected_family and base != selected_family:
                thinking_supported = False
            if thinking_supported:
                cmd, ok = _upsert_cli_flag(cmd, ("--thinking",), thinking)
                changed = changed or ok

        if changed:
            tool_cfg["cmd"] = cmd
            print(f"[RUNTIME] {tool_name}: {shlex.join(cmd)}")


def _resolve_codex_native_binary():
    explicit = os.environ.get("PIPELINE_CODEX_NATIVE_BIN", "").strip()
    if explicit:
        path = os.path.expanduser(explicit)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        return ""

    codex_wrapper = shutil.which("codex")
    if not codex_wrapper:
        return ""
    wrapper_real = os.path.realpath(codex_wrapper)
    suffix = os.path.join("lib", "node_modules", "@openai", "codex", "bin", "codex")
    candidates = []
    if wrapper_real.endswith(suffix):
        prefix = wrapper_real[: -len(suffix)].rstrip(os.sep)
        candidates.append(
            os.path.join(
                prefix,
                "lib",
                "node_modules",
                "@openai",
                "codex",
                "node_modules",
                "@openai",
                "codex-linux-x64",
                "vendor",
                "x86_64-unknown-linux-musl",
                "codex",
                "codex",
            )
        )

    # Fallback: derive from package directory directly.
    pkg_dir = os.path.dirname(os.path.dirname(wrapper_real))
    candidates.append(
        os.path.join(
            pkg_dir,
            "node_modules",
            "@openai",
            "codex-linux-x64",
            "vendor",
            "x86_64-unknown-linux-musl",
            "codex",
            "codex",
        )
    )

    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def apply_codex_native_binary_override(config):
    """Optionally replace node-wrapper 'codex' with native binary to avoid wrapper hangs."""
    enabled = os.environ.get("PIPELINE_CODEX_NATIVE_BIN_ENABLE", "1").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return

    native = _resolve_codex_native_binary()
    if not native:
        return

    tools = config.get("ai_cli_tools", {})
    changed = []
    for tool_name, tool_cfg in tools.items():
        cmd = tool_cfg.get("cmd") or []
        if not cmd:
            continue
        if os.path.basename(cmd[0]) != "codex":
            continue
        cmd = list(cmd)
        cmd[0] = native
        tool_cfg["cmd"] = cmd
        changed.append(tool_name)

    if changed:
        print(f"[INFO] codex native binary enabled for tools: {', '.join(sorted(changed))}")


def read_prompt(prompt_path, parameters, base_dir=None, workspace_root="/work", inject_global_rules=True):
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
    
    # Inject file content from Knowledge Base or other files
    # Syntax: {read_file: path/to/file.md}
    # Using specific regex to handle potential whitespace
    pattern = r'{read_file:\s*([^\{\}]+?)\s*}'
    
    if "read_file:" in template:
        if base_dir:
            def replace_file_content(match):
                rel_path = match.group(1).strip()
                abs_path = os.path.join(base_dir, rel_path)
                if os.path.exists(abs_path):
                    try:
                        with open(abs_path, "r", encoding="utf-8") as f_inc:
                            content = f_inc.read()
                            # Escape braces for format() safety if the file is JSON or code
                            # This prevents Python trying to interpret {key} in the file as a parameter
                            content = content.replace("{", "{{").replace("}", "}}")
                            return content
                    except Exception as e:
                        print(f"[WARN] Failed to read included file {abs_path}: {e}")
                        return f"(Error reading {rel_path})"
                else:
                    print(f"[WARN] Included file not found: {abs_path}")
                    return f"(File not found: {rel_path})"
            
            template = re.sub(pattern, replace_file_content, template)
        else:
            print(f"[WARN] base_dir not provided, skipping file injection in {prompt_path}")

    # Safety net: Remove any remaining tags that might break format()
    # E.g. if regex didn't match but substring exists, or base_dir was None
    if "{read_file:" in template:
        print(f"[WARN] Unresolved {{read_file:...}} tags in {prompt_path}. Replacing with placeholder.")
        # Replace the literal substring to avoid format() KeyError
        # We can't use regex here if it failed before, so simple replace of the key prefix
        # This is a fallback.
        template = template.replace("{read_file:", "(UNRESOLVED_FILE:")

    # --- INJECT GLOBAL PATH RULES ---
    # Scheme A: Workspace Anchoring
    # 2. Inject this into parameters so it can be used in the prompt body if needed
    parameters["workspace_root"] = workspace_root

    if inject_global_rules:
        # 3. Construct the System Mandate using this root
        global_rules = (
            "\n\n**SYSTEM MANDATE: PROFESSIONAL EXECUTION PROTOCOL**\n"
            f"1. WORKSPACE ANCHOR: You are operating inside: {workspace_root}\n"
            "2. NO DIRECTORY CHANGES: You are STRICTLY FORBIDDEN from using 'cd', 'pushd', or changing CWD.\n"
            "3. EXECUTION ROOT: All commands are executed from the Workspace Anchor. Do not verify with 'ls ../'.\n"
            f"4. PATH RESOLUTION: Assume all relative paths (e.g. 'rtl/dut.sv') are relative to {workspace_root}.\n"
            "5. STRICT PROFESSIONALISM: No casual conversation. No 'Here is the code' filler. Output ONLY requested artifacts.\n"
            "6. TOOL USAGE: Prefer tool calls over raw shell where applicable. Do not ask for clarification; make reasonable engineering assumptions.\n"
            "7. ROLE SPECIALIZATION: You must strictly adhere to your assigned role. Do not invent new tools or deviate from the policy-defined toolchain.\n"
            "\n"
        )

        # Prepend to template
        template = global_rules + template

    try:
        return template.format(**parameters)
    except KeyError as exc:
        missing = exc.args[0]
        # Only raise if it's not our safety replacement
        if "UNRESOLVED_FILE" in str(missing):
             return template # Return raw if we messed up
        raise ValueError(f"Missing prompt parameter: {missing}") from exc


def expand_path(path, base_dir=None):
    expanded = os.path.expanduser(path)
    if base_dir and not os.path.isabs(expanded):
        expanded = os.path.join(base_dir, expanded)
    return os.path.abspath(expanded)


def resolve_cli_path(path, workspace=None, base_dir=None):
    expanded = Path(os.path.expandvars(os.path.expanduser(path)))
    if expanded.is_absolute():
        return str(expanded.resolve())
    search_roots = [Path.cwd().resolve()]
    if workspace:
        workspace_path = Path(workspace).resolve()
        search_roots.append(workspace_path)
        search_roots.append(workspace_path.parent)
    if base_dir:
        search_roots.append(Path(base_dir).resolve())
    seen = set()
    for root in search_roots:
        candidate = (root / expanded).resolve()
        if str(candidate) in seen:
            continue
        seen.add(str(candidate))
        if candidate.exists():
            return str(candidate)
    return str((search_roots[0] / expanded).resolve())


def _is_path_token(value):
    if value.startswith(("/", "./", "../", "~")):
        return True
    if "/" in value:
        return True
    return value.endswith(
        (".sv", ".v", ".vh", ".svh", ".py", ".md", ".json", ".f", ".log", ".sh", ".txt", ".yml", ".yaml")
    )


def _resolve_output_paths(parameters, workspace):
    output_paths = {}
    for key, value in parameters.items():
        if key == "log_content":
            continue
        if not isinstance(value, str):
            continue
        if "\n" in value:
            continue
        if len(value) > 512:
            continue
        if not _is_path_token(value):
            continue
        expanded = os.path.expandvars(os.path.expanduser(value))
        if not os.path.isabs(expanded):
            expanded = os.path.abspath(os.path.join(workspace, expanded))
        output_paths[key] = expanded
    return output_paths


def _write_role_log(log_path, role_label, cmd, stdout, stderr, metadata):
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"# role: {role_label}\n")
        log_file.write(f"# time: {datetime.now().isoformat()}\n")
        log_file.write(f"# cmd: {shlex.join(cmd)}\n\n")
        log_file.write("## metadata\n")
        log_file.write(f"config_path: {metadata['config_path']}\n")
        log_file.write(f"base_dir: {metadata['base_dir']}\n")
        log_file.write(f"workspace: {metadata['workspace']}\n")
        log_file.write(f"cwd: {metadata['cwd']}\n")
        log_file.write(f"log_dir: {metadata['log_dir']}\n")
        log_file.write(f"workspace_root: {metadata['workspace_root']}\n")
        output_paths = metadata.get("output_paths", {})
        if output_paths:
            log_file.write("output_paths:\n")
            for key, path in sorted(output_paths.items()):
                log_file.write(f"- {key}: {path}\n")
        else:
            log_file.write("output_paths: (none)\n")
        created_dirs = metadata.get("created_dirs", [])
        if created_dirs:
            log_file.write("created_dirs:\n")
            for path in created_dirs:
                log_file.write(f"- {path}\n")
        else:
            log_file.write("created_dirs: (none)\n")
        log_file.write("\n## stdout\n")
        log_file.write(stdout or "")
        log_file.write("\n\n## stderr\n")
        log_file.write(stderr or "")


def _merge_log_ranges(indices):
    if not indices:
        return []
    ranges = []
    start = indices[0]
    current = indices[0]
    for idx in indices[1:]:
        if idx == current + 1:
            current = idx
        else:
            ranges.append((start, current))
            start = idx
            current = idx
    ranges.append((start, current))
    return ranges


def _format_log_excerpt(lines, ranges):
    output = []
    last_end = -1
    for start, end in ranges:
        if last_end != -1 and start > last_end + 1:
            skipped = start - (last_end + 1)
            output.append("")
            output.append(f"... (skipped {skipped} lines) ...")
            output.append("")
        elif last_end == -1 and start > 0:
            output.append(f"... (skipped {start} lines) ...")
            output.append("")
        output.extend(lines[start : end + 1])
        last_end = end
    return "\n".join(output)


def _read_log_excerpt_fallback(log_path, tail_lines, error_context):
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
            content = lf.read().splitlines()
    except Exception as exc:
        return f"(Failed to read log: {exc})"

    if not content:
        return ""

    total = len(content)
    tail_start = max(0, total - tail_lines)
    indices = set(range(tail_start, total))
    for i, line in enumerate(content):
        if _LOG_ERROR_RE.search(line):
            start = max(0, i - error_context)
            end = min(total, i + error_context + 1)
            indices.update(range(start, end))

    ranges = _merge_log_ranges(sorted(indices))
    return _format_log_excerpt(content, ranges)


def build_docker_command(tool, workspace, env_vars, base_dir):
    cmd = ["docker", "run", "--rm", "-i", "-w", "/work"]
    
    # Pass hostname to ensure auth token decryption works for shared mounts
    cmd.extend(["--hostname", socket.gethostname()])

    cmd.extend(["-v", f"{workspace}:/work:rw"])

    for mount in tool.get("mounts", []):
        source = expand_path(mount["source"], base_dir)
        if not os.path.exists(source):
            continue
        target = mount["target"]
        mode = mount.get("mode", "rw")
        cmd.extend(["-v", f"{source}:{target}:{mode}"])

    cmd.extend(["-e", "HOME=/home/node"])

    # Pass proxy settings if present
    proxy_vars = ["http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]
    for var in proxy_vars:
        if env_vars.get(var):
            cmd.extend(["-e", f"{var}={env_vars[var]}"])

    for key in tool.get("env", []):
        value = env_vars.get(key)
        if value:
            cmd.extend(["-e", f"{key}={value}"])

    image = tool["image"]
    cmd.append(image)
    cmd.extend(tool["cmd"])
    return cmd


def expand_parameters(parameters):
    expanded = {}
    for key, value in parameters.items():
        if isinstance(value, str) and "{" in value and "}" in value:
            try:
                expanded[key] = value.format(**parameters)
            except KeyError:
                expanded[key] = value
        else:
            expanded[key] = value
    return expanded


def build_temp_role(role, overrides):
    params = dict(role.get("parameters", {}))
    if overrides:
        params.update(overrides)
    temp_role = dict(role)
    temp_role["parameters"] = params
    return temp_role


def _run_subprocess_with_heartbeat(
    cmd,
    cwd,
    timeout_sec,
    role_name,
    stdin_text=None,
    waiting_on=None,
):
    """Run subprocess with periodic heartbeat while preserving captured output."""
    first_heartbeat_sec = _env_int("PIPELINE_ROLE_FIRST_HEARTBEAT_SEC", 60, minimum=1)
    heartbeat_sec = _env_int("PIPELINE_ROLE_HEARTBEAT_SEC", 600, minimum=1)
    stalled_warn_sec = _env_int("PIPELINE_ROLE_STALLED_WARN_SEC", 1800, minimum=1)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )

    started = time.monotonic()
    first_round = True
    warned_stalled = False
    wait_label = waiting_on or (os.path.basename(cmd[0]) if cmd else "subprocess")

    def _is_local_tool(label: str) -> bool:
        if not label:
            return False
        if label.endswith("_host"):
            return True
        return label in ("bash", "sh")

    while True:
        elapsed = time.monotonic() - started
        remaining = timeout_sec - elapsed
        if remaining <= 0:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout_sec, output=stdout, stderr=stderr)

        wait_interval = first_heartbeat_sec if first_round else heartbeat_sec
        wait_sec = min(wait_interval, max(1.0, remaining))
        try:
            if first_round:
                stdout, stderr = proc.communicate(input=stdin_text, timeout=wait_sec)
            else:
                stdout, stderr = proc.communicate(timeout=wait_sec)
            return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            elapsed_int = int(time.monotonic() - started)
            if wait_label in _TOOL_NETWORK_PROBES:
                net_ok, net_detail = _check_tool_network(wait_label, timeout_sec=2)
                net_hint = net_detail if net_ok else f"proxy-check failed: {net_detail}"
            elif _is_local_tool(wait_label):
                net_hint = "local tool (network probe skipped)"
            else:
                net_ok, net_detail = _check_proxy_network(timeout_sec=2)
                net_hint = net_detail if net_ok else f"proxy-check failed: {net_detail}"
            print(
                f"[WAIT] {role_name}: waiting for {wait_label} response "
                f"(elapsed={elapsed_int}s/{timeout_sec}s, pid={proc.pid}, net={net_hint})",
                flush=True,
            )
            if (not warned_stalled) and elapsed_int >= stalled_warn_sec:
                if wait_label in _TOOL_NETWORK_PROBES:
                    stall_hint = "Likely upstream AI/proxy stall; check proxy health and service availability."
                elif _is_local_tool(wait_label):
                    stall_hint = "Likely long-running local command or test deadlock; inspect local sim/build logs."
                else:
                    stall_hint = "Likely long-running subprocess; inspect command output and logs."
                print(
                    f"[WARN] {role_name}: prolonged wait (>={stalled_warn_sec}s) while waiting for {wait_label}. "
                    f"{stall_hint}",
                    flush=True,
                )
                warned_stalled = True
            first_round = False


def run_role(role_name, role, tools, workspace, base_dir, log_dir, global_params, config_path, dry_run=False, registry=None):
    if role.get("enabled", True) is False:
        print(f"[SKIP] {role_name}: disabled")
        return True

    tool_name = role["ai_cli"]
    tool = tools[tool_name]
    cli_name = _find_ai_cli_name(tool.get("cmd", []))
    prompt_file = os.path.join(base_dir, role["prompt_file"])
    parameters = dict(global_params)
    parameters.update(role.get("parameters", {}))
    parameters = expand_parameters(parameters)

    skip_if_missing = role.get("skip_if_missing", [])
    for key in skip_if_missing:
        path = parameters.get(key)
        if path and not os.path.exists(os.path.join(workspace, path)):
            print(f"[SKIP] {role_name}: missing {path}")
            return True

    # Check for log injection requirement
    # Optimization: Read file once, use read_prompt logic later
    # But we need to know if log injection is needed to update parameters
    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            raw_template_check = f.read(1024) # Check first 1k chars usually enough for headers? 
            # Actually, {log_content} might be anywhere. Read full.
            f.seek(0)
            raw_template = f.read()
    except Exception as e:
        print(f"[FAIL] {role_name}: Failed to read prompt file {prompt_file}: {e}")
        return False

    if "{log_content}" in raw_template and "log_content" not in parameters:
        error_log_param = parameters.get("error_logs")
        if error_log_param:
            log_path = expand_path(error_log_param, workspace)
            if os.path.exists(log_path):
                try:
                    # Use smart extraction tool if available
                    use_registry_extract = registry and registry.is_available("extract_log_excerpt")
                    extract_tool = os.path.join(workspace, "tools/extract_log_excerpt.py")
                    
                    if use_registry_extract:
                        try:
                            res = registry.run_tool("extract_log_excerpt", [
                                "--input", log_path,
                                "--tail", str(_LOG_EXCERPT_TAIL_LINES),
                                "--context", str(_LOG_EXCERPT_ERROR_CONTEXT)
                            ], timeout=30)
                            if res.returncode == 0:
                                parameters["log_content"] = res.stdout
                            else:
                                print(f"[WARN] Log extractor failed: {res.stderr}")
                                parameters["log_content"] = _read_log_excerpt_fallback(
                                    log_path, _LOG_EXCERPT_TAIL_LINES, _LOG_EXCERPT_ERROR_CONTEXT
                                )
                        except Exception as e:
                            print(f"[WARN] Tool registry failed for extract_log_excerpt: {e}")
                            parameters["log_content"] = _read_log_excerpt_fallback(
                                log_path, _LOG_EXCERPT_TAIL_LINES, _LOG_EXCERPT_ERROR_CONTEXT
                            )

                    elif os.path.exists(extract_tool):
                        res = subprocess.run(
                            [
                                sys.executable,
                                extract_tool,
                                "--input",
                                log_path,
                                "--tail",
                                str(_LOG_EXCERPT_TAIL_LINES),
                                "--context",
                                str(_LOG_EXCERPT_ERROR_CONTEXT),
                            ],
                            capture_output=True, text=True, timeout=30
                        )
                        if res.returncode == 0:
                            parameters["log_content"] = res.stdout
                        else:
                            print(f"[WARN] Log extractor failed: {res.stderr}")
                            parameters["log_content"] = _read_log_excerpt_fallback(
                                log_path, _LOG_EXCERPT_TAIL_LINES, _LOG_EXCERPT_ERROR_CONTEXT
                            )
                    else:
                        parameters["log_content"] = _read_log_excerpt_fallback(
                            log_path, _LOG_EXCERPT_TAIL_LINES, _LOG_EXCERPT_ERROR_CONTEXT
                        )
                except Exception as e:
                    print(f"[WARN] Failed to read log for injection: {e}")
                    parameters["log_content"] = f"(Failed to read log: {e})"
            else:
                parameters["log_content"] = "(Log file not found)"
        else:
            parameters["log_content"] = "(No error_logs parameter defined)"

    try:
        # Scheme A: Workspace Anchoring
        # 1. Determine the absolute workspace root seen by the agent
        if tool["runner"] == "docker":
            workspace_root_val = "/work"
        else:
            # For host, it's the absolute path to the workspace
            workspace_root_val = workspace

        # Use new read_prompt with base_dir support
        # Passing base_dir allows {read_file:...} to resolve paths relative to repo root
        inject_global_rules = tool.get("cmd", [])[:1] != ["bash"]
        prompt = read_prompt(
            prompt_file,
            parameters,
            base_dir,
            workspace_root=workspace_root_val,
            inject_global_rules=inject_global_rules,
        )
    except ValueError as e:
        print(f"[FAIL] {role_name}: Prompt formatting error: {e}")
        return False

    if tool["runner"] == "docker":
        cmd = build_docker_command(tool, workspace, os.environ, base_dir)
        cwd = None
    elif tool["runner"] == "host":
        cmd = list(tool["cmd"])  # Make a copy to avoid modifying the original
        cwd = workspace
    else:
        raise ValueError(f"Unknown runner: {tool['runner']}")

    # For tools that don't use stdin (e.g. opencode), append prompt as argument
    use_stdin = tool.get("stdin", True)
    if not use_stdin:
        cmd.append(prompt)

    log_path = os.path.join(log_dir, f"{role_name}.log")
    log_dir_created = not os.path.isdir(log_dir)
    os.makedirs(log_dir, exist_ok=True)

    output_paths = _resolve_output_paths(parameters, workspace)
    output_dirs = sorted({os.path.dirname(path) for path in output_paths.values() if path})
    missing_output_dirs = [path for path in output_dirs if path and not os.path.isdir(path)]
    created_dirs = []
    if log_dir_created:
        created_dirs.append(log_dir)
    cwd_display = workspace_root_val if tool["runner"] == "docker" else cwd

    # Get timeout from role or global params (default 600s)
    timeout_sec = role.get("timeout", global_params.get("default_timeout", 600))

    if dry_run:
        # Show prompt preview for both stdin and arg modes
        prompt_preview = prompt[:80].replace('\n', ' ') + "..." if len(prompt) > 80 else prompt.replace('\n', ' ')
        
        if not use_stdin:
            cmd_display = cmd[:-1]  # Exclude the prompt argument
            print(f"[DRY RUN] {role_name}: {shlex.join(cmd_display)} '<prompt: {len(prompt)} chars>' (timeout={timeout_sec}s)")
        else:
            print(f"[DRY RUN] {role_name}: {shlex.join(cmd)} '<stdin prompt: {len(prompt)} chars>' (timeout={timeout_sec}s)")
            
        print(f"[DRY RUN] Prompt preview: {prompt_preview}")
        print(f"[DRY RUN] Parameters: {json.dumps(parameters, indent=2)}")
        return True

    print(f"[RUN] {role_name}: {shlex.join(cmd)}")
    try:
        result = _run_subprocess_with_heartbeat(
            cmd,
            cwd=cwd,
            timeout_sec=timeout_sec,
            role_name=role_name,
            stdin_text=prompt if use_stdin else None,
            waiting_on=cli_name or tool_name,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"[FAIL] {role_name}: Timed out after {timeout_sec}s")
        created_dirs.extend([path for path in missing_output_dirs if os.path.isdir(path)])
        metadata = {
            "config_path": config_path,
            "base_dir": base_dir,
            "workspace": workspace,
            "cwd": cwd_display,
            "log_dir": log_dir,
            "workspace_root": workspace_root_val,
            "output_paths": output_paths,
            "created_dirs": created_dirs,
        }
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        _write_role_log(log_path, f"{role_name} (TIMEOUT)", cmd, stdout, stderr, metadata)
        return False

    if cli_name:
        auth_failed, auth_detail = _detect_auth_failure(result.stdout, result.stderr)
        if auth_failed:
            detail = auth_detail or "authentication required"
            print(f"[FAIL] {role_name}: {cli_name} authentication failure detected: {detail}")
            if result.returncode == 0:
                result.returncode = 1
        net_failed, net_detail = _detect_network_failure(result.stdout, result.stderr)
        if net_failed:
            detail = net_detail or "network unavailable"
            print(f"[FAIL] {role_name}: {cli_name} network failure detected: {detail}")
            print("       [FIX] Ensure outbound HTTPS is available for AI CLI service endpoints.")
            print("       [FIX] OpenChipFlow depends on live LLM calls and requires network access.")
            if result.returncode == 0:
                result.returncode = 1

    # Check for error log file as failure indicator
    error_log_param = parameters.get("error_logs")
    if error_log_param:
        # Determine absolute path to log
        if os.path.isabs(error_log_param):
            abs_log_path = error_log_param
        else:
            abs_log_path = os.path.join(workspace, error_log_param)
            
        if os.path.exists(abs_log_path) and os.path.getsize(abs_log_path) > 0:
            print(f"[FAIL] {role_name}: Error log found at {abs_log_path}")
            if result.returncode == 0:
                result.returncode = 1

    created_dirs.extend([path for path in missing_output_dirs if os.path.isdir(path)])
    metadata = {
        "config_path": config_path,
        "base_dir": base_dir,
        "workspace": workspace,
        "cwd": cwd_display,
        "log_dir": log_dir,
        "workspace_root": workspace_root_val,
        "output_paths": output_paths,
        "created_dirs": created_dirs,
    }
    _write_role_log(log_path, role_name, cmd, result.stdout, result.stderr, metadata)

    if result.returncode != 0:
        if role.get("allow_fail", False):
            print(f"[WARN] {role_name}: exit {result.returncode} (allow_fail)")
            return True
        print(f"[FAIL] {role_name}: exit {result.returncode}")
        return False

    print(f"[OK] {role_name}")
    return True


def run_fix_loop(
    role_name,
    loop_config,
    roles,
    tools,
    workspace,
    base_dir,
    log_dir,
    global_params,
    config_path,
    dry_run,
    item_params=None,
    label=None,
    registry=None,
):
    max_retries = loop_config.get("max_retries", 3)
    fixer_name = loop_config["fixer_role"]
    rerun_name = loop_config["rerun_role"]
    label_suffix = f" {label}" if label else ""

    print(f"[INFO] Entering fix loop for {role_name}{label_suffix} (max_retries={max_retries})")

    for i in range(max_retries):
        print(f"[LOOP] Attempt {i+1}/{max_retries}")

        fixer_role = build_temp_role(roles[fixer_name], item_params)
        rerun_role = build_temp_role(roles[rerun_name], item_params)

        had_changes_before = _git_has_changes(workspace) if not dry_run else False

        fixer_ok = run_role(
            fixer_name,
            fixer_role,
            tools,
            workspace,
            base_dir,
            log_dir,
            global_params,
            config_path,
            dry_run,
            registry=registry,
        )

        had_changes_after = _git_has_changes(workspace) if not dry_run else False
        if not dry_run and fixer_ok and (had_changes_after == had_changes_before):
            _auto_apply_patch_from_log(fixer_name, fixer_role, log_dir, workspace)

        rerun_ok = run_role(
            rerun_name,
            rerun_role,
            tools,
            workspace,
            base_dir,
            log_dir,
            global_params,
            config_path,
            dry_run,
            registry=registry,
        )

        if rerun_ok:
            print(f"[LOOP] Passed on attempt {i+1}")
            return True

    print(f"[LOOP] Failed after {max_retries} attempts")
    
    # Automatic Escalation Trigger + HITL Escalation Request
    run_id = global_params.get("run_id") or global_params.get("timestamp") or "unknown_run"
    log_file = os.path.join(log_dir, f"{role_name}.log")
    escalation_packet_path = os.path.join(workspace, "artifacts", "escalations", f"{run_id}_escalation.json")

    use_registry_escalation = registry and registry.is_available("escalation_packet")
    escalation_script = os.path.join(workspace, "tools/escalation_packet.py")
    
    if use_registry_escalation:
        print(f"[ESCALATION] Generating escalation packet for {role_name}...")
        try:
            registry.run_tool("escalation_packet", [
                "--run-id", run_id,
                "--stage", role_name,
                "--log-file", log_file,
                "--workspace", workspace,
                "--output", escalation_packet_path,
            ], timeout=30)
        except Exception as e:
            print(f"[WARN] Escalation packet generation failed: {e}")
    elif os.path.exists(escalation_script):
        print(f"[ESCALATION] Generating escalation packet for {role_name}...")
        try:
            subprocess.run(
                [
                    sys.executable,
                    escalation_script,
                    "--run-id", run_id,
                    "--stage", role_name,
                    "--log-file", log_file,
                    "--workspace", workspace,
                    "--output", escalation_packet_path,
                ],
                capture_output=False,
                timeout=30,
            )
        except Exception as e:
            print(f"[WARN] Escalation packet generation failed: {e}")

    use_registry_hitl = registry and registry.is_available("request_hitl")
    hitl_request_script = os.path.join(workspace, "tools", "request_hitl.py")

    if use_registry_hitl:
        print(f"[HITL] Escalating {role_name} to pending HITL review...")
        try:
            registry.run_tool("request_hitl", [
                "--run-id", run_id,
                "--stage", role_name,
                "--reason", f"fix loop exceeded max_retries={max_retries}",
                "--escalation-packet", escalation_packet_path,
                "--workspace", workspace,
            ], timeout=30)
        except Exception as e:
            print(f"[WARN] HITL escalation request generation failed: {e}")
    elif os.path.exists(hitl_request_script):
        print(f"[HITL] Escalating {role_name} to pending HITL review...")
        try:
            subprocess.run(
                [
                    sys.executable,
                    hitl_request_script,
                    "--run-id", run_id,
                    "--stage", role_name,
                    "--reason", f"fix loop exceeded max_retries={max_retries}",
                    "--escalation-packet", escalation_packet_path,
                    "--workspace", workspace,
                ],
                capture_output=False,
                timeout=30,
            )
        except Exception as e:
            print(f"[WARN] HITL escalation request generation failed: {e}")

    return False


def scan_test_modules(workspace, test_dir_rel="tests"):
    """Scan workspace for test modules (tests/test_*.py) to support regression filtering."""
    test_dir = os.path.join(workspace, test_dir_rel)
    modules = []
    if os.path.isdir(test_dir):
        try:
            for f in os.listdir(test_dir):
                if f.startswith("test_") and f.endswith(".py"):
                    name = f[:-3]
                    # Convert file path to python module path (e.g. tests.test_ai)
                    modules.append(f"{test_dir_rel}.{name}")
        except Exception as e:
            print(f"[WARN] Failed to scan test directory {test_dir}: {e}")
    return modules


def main():
    parser = argparse.ArgumentParser(description="Run AI CLI pipeline")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--role", help="Run a single role by name")
    parser.add_argument("--workflow", help="Run a specific workflow defined in config (e.g. 'plan', 'implement')")
    parser.add_argument(
        "--handoff-manifest",
        default=os.environ.get("CHIPFLOW_HANDOFF_MANIFEST"),
        help="path to artifact_handoff_manifest JSON for incremental workflows",
    )
    parser.add_argument(
        "--handoff-root",
        default=os.environ.get("CHIPFLOW_HANDOFF_ROOT"),
        help="path to a raw handoff directory for intake validation workflows",
    )
    parser.add_argument(
        "--source-requirements-root",
        default=os.environ.get("CHIPFLOW_SOURCE_REQUIREMENTS_ROOT"),
        help="optional path to source_requirements directory used for semantic handoff review",
    )
    parser.add_argument(
        "--spec-source",
        default=os.environ.get("CHIPFLOW_SPEC_SOURCE"),
        help="path to an external spec.md to use instead of the default inbox spec",
    )
    parser.add_argument(
        "--session-root",
        default=os.environ.get("CHIPFLOW_SESSION_ROOT"),
        help="optional session root under the pipeline workspace for handoff/incremental flows",
    )
    parser.add_argument(
        "--target-state",
        default=os.environ.get("CHIPFLOW_TARGET_STATE"),
        help="optional handoff target state override",
    )
    parser.add_argument(
        "--backend-policy",
        default=os.environ.get("CHIPFLOW_BACKEND_POLICY"),
        help="optional backend policy override for incremental flows",
    )
    parser.add_argument(
        "--semantic-review-mode",
        default=os.environ.get("CHIPFLOW_SEMANTIC_REVIEW_MODE"),
        help="semantic review mode for handoff intake: off, auto, or required",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without execution")
    parser.add_argument("--preflight", action="store_true", help="Run quick preflight checks and exit")
    parser.add_argument("--model", default=None, help="runtime model override for AI CLIs")
    parser.add_argument("--variant", default=None, help="runtime variant override for AI CLIs")
    parser.add_argument("--thinking", default=None, help="runtime thinking override for AI CLIs")
    parser.add_argument("--capabilities", default=None, help="optional capabilities.json path")
    args = parser.parse_args()

    config_path = expand_path(os.path.join(os.path.dirname(__file__), args.config))
    base_dir = os.path.dirname(config_path)
    config = load_config(config_path)
    workspace = expand_path(os.path.join(base_dir, config["workspace"]))
    apply_codex_native_binary_override(config)

    # Initialize ToolRegistry
    registry = None
    if ToolRegistry:
        registry = ToolRegistry(workspace)

    apply_runtime_ai_cli_overrides(
        config,
        model=args.model,
        variant=args.variant,
        thinking=args.thinking,
        capability_path=args.capabilities,
        workspace=workspace,
        base_dir=base_dir,
    )

    global_params = dict(config.get("global_parameters", {}))

    # Add timestamp to global parameters for branching
    global_params["timestamp"] = datetime.now().strftime("%Y%m%d_%H%M")

    case_id_env = config.get("case_id_env")
    if case_id_env:
        case_id = os.environ.get(case_id_env)
        if case_id:
            global_params["case_id"] = case_id

    resolved_handoff_root = (
        resolve_cli_path(args.handoff_root, workspace=workspace, base_dir=base_dir)
        if args.handoff_root
        else ""
    )
    resolved_handoff_manifest = (
        resolve_cli_path(args.handoff_manifest, workspace=workspace, base_dir=base_dir)
        if args.handoff_manifest
        else ""
    )
    resolved_source_requirements_root = (
        resolve_cli_path(args.source_requirements_root, workspace=workspace, base_dir=base_dir)
        if args.source_requirements_root
        else ""
    )
    resolved_spec_source = (
        resolve_cli_path(args.spec_source, workspace=workspace, base_dir=base_dir)
        if args.spec_source
        else ""
    )
    resolved_session_root = (
        resolve_cli_path(args.session_root, workspace=workspace, base_dir=base_dir)
        if args.session_root
        else ""
    )

    if args.handoff_root:
        global_params["handoff_root_path"] = resolved_handoff_root
    if args.handoff_manifest:
        global_params["handoff_manifest_path"] = resolved_handoff_manifest
    if args.source_requirements_root:
        global_params["source_requirements_root_path"] = resolved_source_requirements_root
    if args.spec_source:
        global_params["inbox_spec_path"] = resolved_spec_source
    if args.target_state:
        global_params["target_state"] = args.target_state
    if args.backend_policy:
        global_params["backend_policy"] = args.backend_policy
    if args.semantic_review_mode:
        global_params["semantic_review_mode"] = args.semantic_review_mode
    if resolved_session_root:
        session_root_abs = Path(resolved_session_root).resolve()
        workspace_root = Path(workspace).resolve()
        try:
            session_root_rel = str(session_root_abs.relative_to(workspace_root))
        except ValueError:
            print(f"[FAIL] session-root must resolve inside workspace {workspace_root}: {session_root_abs}")
            sys.exit(1)
        session_workspace_rel = f"{session_root_rel}/workspace"
        session_handoff_rel = f"{session_root_rel}/handoff"
        global_params["session_root_path"] = session_root_rel
        global_params["session_workspace_root"] = session_workspace_rel
        global_params["handoff_output_dir"] = session_handoff_rel
        global_params["handoff_context_path"] = f"{session_handoff_rel}/handoff_context.json"
        if resolved_handoff_root or resolved_handoff_manifest:
            global_params["case_schedule_path"] = f"{session_workspace_rel}/artifacts/case_schedule.json"
            global_params["testcase_validation_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/testcase_validation.json"
            )
            global_params["trace_matrix_md_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/req_trace_matrix.md"
            )
            global_params["trace_matrix_json_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/req_trace_matrix.json"
            )
            global_params["verify_report_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/verify.md"
            )
            global_params["sim_fail_log_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/sim_fail.log"
            )
            global_params["fix_notes_sim_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/fix_notes_sim.md"
            )
            global_params["sim_failures_dir"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/failures"
            )
            global_params["regress_fail_log_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/regress_fail.log"
            )
            global_params["fix_notes_regress_path"] = (
                f"{session_workspace_rel}/ai_cli_pipeline/verification/fix_notes_regress.md"
            )
            global_params["incremental_compliance_out_path"] = (
                f"{session_root_rel}/ops/incremental_compliance_{global_params['timestamp']}.json"
            )
            global_params["incremental_contract_out_path"] = (
                f"{session_root_rel}/ops/incremental_contract_{global_params['timestamp']}.json"
            )

    intake_role = args.role == "handoff_intake_validator"
    intake_workflow = args.workflow == "handoff_intake"
    eager_handoff_context = bool(resolved_handoff_manifest) and not (intake_role or intake_workflow)

    if eager_handoff_context:
        try:
            manifest_data, manifest_file = load_handoff_manifest(resolved_handoff_manifest)
            handoff_context = build_handoff_context(
                manifest_data,
                manifest_file,
                workspace,
                context_output=global_params.get(
                    "handoff_context_path", "artifacts/handoff/handoff_context.json"
                ),
            )
        except HandoffError as exc:
            print(f"[FAIL] handoff manifest invalid: {exc}")
            sys.exit(1)
        global_params.update(handoff_context.get("derived_global_params", {}))
        global_params.setdefault("delivery_state", handoff_context.get("delivery_state", ""))
        if not os.environ.get(case_id_env or "", ""):
            global_params["case_id"] = handoff_context.get("case_id", global_params["case_id"])
        print(
            "[INFO] Loaded handoff manifest:",
            global_params.get("handoff_manifest_path", resolved_handoff_manifest),
        )
        print(
            f"[INFO] Handoff case_id={handoff_context.get('case_id')} "
            f"delivery_state={handoff_context.get('delivery_state')}"
        )

    if resolved_spec_source:
        print(f"[INFO] Using external spec source: {resolved_spec_source}")

    roles = config["roles"]
    workflows = config.get("workflows", {})
    if args.role and args.role not in roles:
        print(f"[FAIL] Role '{args.role}' not found in config. Available: {', '.join(sorted(roles.keys()))}")
        sys.exit(1)
    if args.workflow and args.workflow not in workflows:
        print(f"[FAIL] Workflow '{args.workflow}' not found in config. Available: {', '.join(workflows.keys())}")
        sys.exit(1)

    role_filter = [args.role] if args.role else (workflows[args.workflow] if args.workflow else None)

    if args.preflight:
        # Default to checking only tools required by execution_order.
        # Set PIPELINE_PREFLIGHT_ALL_TOOLS=1 to enforce full ai_cli_tools validation.
        check_all_tools = os.environ.get("PIPELINE_PREFLIGHT_ALL_TOOLS", "0") == "1"
        ok = preflight_check(config, base_dir, role_filter=role_filter, check_all_tools=check_all_tools)
        sys.exit(0 if ok else 1)

    if not args.dry_run:
        if not preflight_check(config, base_dir, role_filter=role_filter):
            sys.exit(1)

    log_dir = expand_path(os.path.join(workspace, config["log_dir"]))

    dv_metadata_path = os.path.join(workspace, "artifacts/dv_metadata.json")
    
    if args.workflow:
        if args.workflow == "incremental_verify_ready" and not resolved_handoff_manifest:
            print("[FAIL] incremental_verify_ready requires --handoff-manifest or CHIPFLOW_HANDOFF_MANIFEST")
            sys.exit(1)
        if args.workflow == "handoff_intake" and not (resolved_handoff_root or resolved_handoff_manifest):
            print("[FAIL] handoff_intake requires --handoff-root or --handoff-manifest")
            sys.exit(1)
        order = workflows[args.workflow]
        print(f"[INFO] Running workflow: {args.workflow}")
    elif args.role:
        order = [args.role]
    else:
        order = config["execution_order"]

    failed_modules = set()
    had_fail = False

    for role_name in order:
        if args.role and role_name != args.role:
            continue
        role = roles[role_name]

        # Dynamic Loop Logic (e.g. testplan dispatcher)
        if "drive_loop_from_file" in role:
            loop_file_rel = role["drive_loop_from_file"]
            if isinstance(loop_file_rel, str) and "{" in loop_file_rel and "}" in loop_file_rel:
                try:
                    loop_file_rel = loop_file_rel.format(**global_params)
                except KeyError:
                    pass
            # loop_file path is relative to workspace (since dispatcher writes to artifacts)
            loop_file_path = os.path.join(workspace, loop_file_rel)
            
            if not os.path.exists(loop_file_path):
                if args.dry_run:
                    print(f"[DRY RUN] {role_name}: Would loop over {loop_file_rel} (file not found yet)")
                    continue
                print(f"[SKIP] {role_name}: Drive loop file not found: {loop_file_path}")
                continue

            # Optimization C: Clean and validate JSON before loading
            cleaner_tool = os.path.join(workspace, "tools/json_cleaner.py")
            if os.path.exists(cleaner_tool):
                subprocess.run([sys.executable, cleaner_tool, loop_file_path], capture_output=True)

            try:
                with open(loop_file_path, "r", encoding="utf-8") as f:
                    loop_items = json.load(f)
            except Exception as e:
                print(f"[FAIL] {role_name}: Failed to load loop file {loop_file_path}: {e}")
                had_fail = True
                if config.get("stop_on_fail", True): break
                continue

            if not isinstance(loop_items, list):
                print(f"[FAIL] {role_name}: Loop file must contain a JSON list")
                had_fail = True
                if config.get("stop_on_fail", True): break
                continue

            print(f"[INFO] {role_name}: Starting dynamic loop ({len(loop_items)} items) from {loop_file_rel}")
            
            loop_ok = True
            loop_failures = []
            for idx, item in enumerate(loop_items):
                # item is expected to be a dict of parameters to override
                # e.g. {"case_id": "T_001", "testcase": "run_basic"}
                
                # Merge item params into role params temporarily
                # We do a shallow merge on top of existing parameters
                original_params = role.get("parameters", {})
                merged_params = dict(original_params)
                merged_params.update(item)
                
                # Create a temporary role config for this iteration
                temp_role = dict(role)
                temp_role["parameters"] = merged_params
                
                print(f"[LOOP] {role_name} iteration {idx+1}/{len(loop_items)}: {item.get('case_id', 'unknown')}")
                
                ok = run_role(
                    role_name,
                    temp_role,
                    config["ai_cli_tools"],
                    workspace,
                    base_dir,
                    log_dir,
                    global_params,
                    config_path,
                    args.dry_run,
                    registry=registry,
                )

                if not ok and "fix_loop_config" in role:
                    loop_config = role["fix_loop_config"]
                    case_label = item.get("case_id", "unknown")
                    ok = run_fix_loop(
                        role_name,
                        loop_config,
                        roles,
                        config["ai_cli_tools"],
                        workspace,
                        base_dir,
                        log_dir,
                        global_params,
                        config_path,
                        args.dry_run,
                        item_params=item,
                        label=f"(case {case_label})",
                        registry=registry,
                    )

                    if not ok:
                        for idx_fb, fallback in enumerate(loop_config.get("fallback_fixers", [])):
                            ok = run_fix_loop(
                                role_name,
                                fallback,
                                roles,
                                config["ai_cli_tools"],
                                workspace,
                                base_dir,
                                log_dir,
                                global_params,
                                config_path,
                                args.dry_run,
                                item_params=item,
                                label=f"(case {case_label} fallback-{idx_fb+1})",
                                registry=registry,
                            )
                            if ok:
                                break

                if not ok:
                    for action_name in role.get("failure_actions", []):
                        action_role = build_temp_role(roles[action_name], item)
                        run_role(
                            action_name,
                            action_role,
                            config["ai_cli_tools"],
                            workspace,
                            base_dir,
                            log_dir,
                            global_params,
                            config_path,
                            args.dry_run,
                        )

                    loop_failures.append(item.get("case_id", "unknown"))
                    
                    # Track failing module to exclude from regression
                    fail_mod = item.get("test_module")
                    if not fail_mod:
                        # Fallback to role default
                        fail_mod = role.get("parameters", {}).get("test_module")
                    if fail_mod:
                        failed_modules.add(fail_mod)

                    loop_ok = False
                    if config.get("stop_on_fail", True) and not role.get("continue_on_fail", False):
                        break

                # Execute post-iteration actions (e.g. commit)
                if "iteration_post_actions" in role:
                    for action_name in role["iteration_post_actions"]:
                        action_role = build_temp_role(roles[action_name], item)
                        run_role(
                            action_name,
                            action_role,
                            config["ai_cli_tools"],
                            workspace,
                            base_dir,
                            log_dir,
                            global_params,
                            config_path,
                            args.dry_run,
                        )
            
            if loop_failures:
                print(f"[WARN] {role_name}: failures in {len(loop_failures)} cases: {', '.join(loop_failures)}")
                had_fail = True

            if not loop_ok and config.get("stop_on_fail", True) and not role.get("continue_on_fail", False):
                break
            continue

        # Logic to exclude failed modules from regression
        if role_name == "regress_runner":
            dv_metadata = {}
            if os.path.exists(dv_metadata_path):
                try:
                    with open(dv_metadata_path, "r") as f:
                        dv_metadata = json.load(f)
                        print(f"[INFO] Loaded DV metadata: {dv_metadata}")
                except Exception as e:
                    print(f"[WARN] Failed to load DV metadata: {e}")
            # Check if regr_modules is already explicitly set (e.g. via manual config or CLI override)
            explicit_modules = role.get("parameters", {}).get("regr_modules", "")
            if isinstance(explicit_modules, str) and "{" in explicit_modules and "}" in explicit_modules:
                try:
                    explicit_modules = explicit_modules.format(**global_params)
                except KeyError:
                    explicit_modules = ""
            if isinstance(explicit_modules, str):
                explicit_modules = explicit_modules.strip()
            
            if explicit_modules:
                print(f"[INFO] Using explicit regression modules: {explicit_modules}")
            
            elif dv_metadata.get("test_module"):
                # Use metadata from DV Agent if available
                meta_module = dv_metadata["test_module"]
                if "parameters" not in role:
                    role["parameters"] = {}
                role["parameters"]["regr_modules"] = meta_module
                print(f"[INFO] Using regression module from DV metadata: {meta_module}")
                
            elif failed_modules:
                print(f"[INFO] Excluding failed modules from regression: {sorted(list(failed_modules))}")
                all_mods = scan_test_modules(workspace)
                if all_mods:
                    safe_mods = [m for m in all_mods if m not in failed_modules]
                    if not safe_mods:
                        print("[WARN] All test modules have failures! Skipping regression runner to avoid empty run error.")
                        continue
                    
                    # Override regr_modules
                    if "parameters" not in role:
                        role["parameters"] = {}
                    role["parameters"]["regr_modules"] = " ".join(safe_mods)
                    print(f"[INFO] Regression will run on: {role['parameters']['regr_modules']}")
                else:
                    print("[WARN] Could not scan test modules to filter regression. Proceeding with default (all).")

        # PR gate: block/skip pr_submit when Gitee auth is not ready
        if role_name == "pr_submit" and not args.dry_run:
            gitee_ok, gitee_detail = _check_gitee_auth_status()
            if not gitee_ok:
                print(f"[FAIL][TOOLING] pr_submit blocked: gitee auth not ready ({gitee_detail})")
                print("[FIX][TOOLING] run `gitee auth --help` and configure auth token/code, then verify with `gitee auth status`.")
                had_fail = True
                if config.get("stop_on_fail", True):
                    break
                else:
                    continue
            current_branch = _current_git_branch(workspace)
            if current_branch in ("master", "main"):
                print(f"[FAIL][TOOLING] pr_submit blocked: still on protected branch {current_branch}")
                print("[FIX][TOOLING] ensure `case_branch` runs before implement roles, or switch to a dev branch before starting the workflow.")
                had_fail = True
                if config.get("stop_on_fail", True):
                    break
                else:
                    continue

        # Standard Single Run
        ok = run_role(
            role_name,
            role,
            config["ai_cli_tools"],
            workspace,
            base_dir,
            log_dir,
            global_params,
            config_path,
            args.dry_run,
            registry=registry,
        )

        # Fix Loop Logic
        if not ok and "fix_loop_config" in role:
            loop_config = role["fix_loop_config"]
            ok = run_fix_loop(
                role_name,
                loop_config,
                roles,
                config["ai_cli_tools"],
                workspace,
                base_dir,
                log_dir,
                global_params,
                config_path,
                args.dry_run,
                registry=registry,
            )

            if not ok:
                for idx_fb, fallback in enumerate(loop_config.get("fallback_fixers", [])):
                    ok = run_fix_loop(
                        role_name,
                        fallback,
                        roles,
                        config["ai_cli_tools"],
                        workspace,
                        base_dir,
                        log_dir,
                        global_params,
                        config_path,
                        args.dry_run,
                        label=f"(fallback-{idx_fb+1})",
                        registry=registry,
                    )
                    if ok:
                        break

        if not ok:
            for action_name in role.get("failure_actions", []):
                action_role = build_temp_role(roles[action_name], None)
                run_role(
                    action_name,
                    action_role,
                    config["ai_cli_tools"],
                    workspace,
                    base_dir,
                    log_dir,
                    global_params,
                    config_path,
                    args.dry_run,
                    registry=registry,
                )
            had_fail = True

        if not ok and config.get("stop_on_fail", True):
            break

    if had_fail:
        print("[FAIL] Pipeline completed with failures.")
        sys.exit(1)


if __name__ == "__main__":
    main()

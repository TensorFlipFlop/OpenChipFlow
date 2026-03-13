#!/usr/bin/env python3
import shutil
import os
import sys
import subprocess
import importlib.util

_REPO_TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
if _REPO_TOOLS_DIR not in sys.path:
    sys.path.insert(0, _REPO_TOOLS_DIR)

try:
    from gitee_auth import check_gitee_auth
except ImportError:
    check_gitee_auth = None

def check_command(cmd, name=None):
    if name is None:
        name = cmd
    path = shutil.which(cmd)
    if path:
        print(f"[OK] {name}: found at {path}")
        return True
    else:
        print(f"[FAIL] {name}: not found in PATH")
        return False

def check_python_module(module_name):
    if importlib.util.find_spec(module_name):
        print(f"[OK] Python module '{module_name}': installed")
        return True
    else:
        print(f"[FAIL] Python module '{module_name}': not installed")
        return False

def check_env_var(var):
    if os.environ.get(var):
        print(f"[OK] Env var '{var}': set")
        return True
    else:
        print(f"[WARN] Env var '{var}': not set (required for corresponding AI tool)")
        return False

def check_verilator():
    try:
        result = subprocess.run(["verilator", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[OK] Verilator: {result.stdout.strip()}")
            return True
        else:
            print(f"[FAIL] Verilator: command failed")
            return False
    except FileNotFoundError:
        print(f"[FAIL] Verilator: not found")
        return False


def check_gitee_cli():
    # 1. Check existence
    path = shutil.which("gitee")
    if not path:
        print(f"[WARN] Gitee CLI: not found in PATH (Automated PRs will be skipped)")
        print("       [FIX] Install gitee CLI and ensure `gitee` is in PATH.")
        return False

    print(f"[OK] Gitee CLI: found at {path}")

    if check_gitee_auth is None:
        print("[WARN] Gitee CLI: auth helper unavailable (gitee_auth import failed)")
        return False

    auth = check_gitee_auth(
        cli_timeout_sec=5,
        api_timeout_sec=5,
        user_agent="openchipflow-check-env/1.0",
    )
    if auth.get("ok", False):
        if auth.get("method") == "gitee auth status":
            print(f"[OK] Gitee CLI: authenticated")
        else:
            print(f"[OK] Gitee Auth: {auth.get('detail')} (fallback from gitee auth status)")
        return True

    print(f"[WARN] Gitee CLI: not authenticated or unavailable (Exit code {auth.get('status_rc')})")
    tail = auth.get("status_tail", "")
    if tail:
        print(f"       Output: {tail}")
    api_detail = auth.get("api_detail", "")
    if api_detail:
        print(f"       Fallback: {api_detail}")
    print("       [FIX] Run `gitee auth --help` and complete auth (授权码/令牌).")
    print("       [FIX] Confirm ~/.gitee/config.yml exists after auth.")
    return False

def main():
    print("=== AI CLI Pipeline Environment Check ===\n")
    
    # 1. Core Tools
    print("--- Core Tools ---")
    all_good = True
    all_good &= check_command("make")
    if not check_command("docker", "Docker (optional if running on host)"):
        print("     [WARN] Docker not found. Host-mode pipeline can still run.")
    all_good &= check_command("git")
    
    # Verilator is critical for SIM, but maybe user uses another simulator?
    # We mark it as FAIL but maybe not block 'all_good' if we want to allow partial checks?
    # For now, let's keep it strict for Verilator as it is the default sim.
    if not check_verilator():
        all_good = False
        print("     [FIX] Install Verilator: 'sudo apt install verilator' or build from source.")
        
    if not check_command("verible-verilog-format", "Verible Format"):
        # Verible is optional for function but good for quality
        print("     [WARN] Verible not found. Code formatting will be skipped.")
        print("     [FIX] Download Verible binaries from: https://github.com/chipsalliance/verible/releases")

    check_gitee_cli() 
    print("")

    # 2. AI CLI Tools
    print("--- AI CLI Tools ---")
    require_claude = os.environ.get("CHECK_ENV_REQUIRE_CLAUDE", "0") == "1"
    required_tools = ["codex", "gemini", "opencode"]
    optional_tools = ["claude"]

    if require_claude:
        required_tools.append("claude")
        optional_tools = []

    for tool in required_tools:
        if check_command(tool):
            print(f"     [NOTE] Ensure you are logged in: '{tool} login'")
        else:
            all_good = False
            if tool == "claude":
                print("     [FIX] Install via npm: 'npm install -g @anthropic-ai/claude-code'")
            elif tool == "codex":
                print("     [FIX] Install via npm: 'npm install -g @openai/codex'")
            elif tool == "gemini":
                print("     [FIX] Install via npm: 'npm install -g @google/gemini-cli'")
            elif tool == "opencode":
                print("     [FIX] Install via npm: 'npm install -g opencode-ai'")

    for tool in optional_tools:
        if check_command(tool):
            print(f"     [NOTE] Optional tool available: '{tool}'")
        else:
            print(f"     [WARN] Optional tool missing: {tool} (set CHECK_ENV_REQUIRE_CLAUDE=1 to enforce)")
    print("")

    # 3. Python Environment
    print("--- Python Environment ---")
    all_good &= check_python_module("cocotb")
    all_good &= check_python_module("cocotb_bus")
    if not importlib.util.find_spec("cocotb"):
        print("     [FIX] Install via pip: 'pip install cocotb cocotb-bus'")
    print("")

    if all_good:
        print("=== Environment looks good! ===")
        sys.exit(0)
    else:
        print("=== Some checks failed. Please review above. ===")
        sys.exit(1)

if __name__ == "__main__":
    main()

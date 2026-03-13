#!/usr/bin/env bash
set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}"
REPORT_NAME="${REPORT:-tool_config_report.txt}"
if [[ "${REPORT_NAME}" = /* ]]; then
  REPORT_PATH="${REPORT_NAME}"
else
  REPORT_PATH="${ROOT_DIR}/${REPORT_NAME}"
fi
REQUIRE_DOCKER="${REQUIRE_DOCKER:-1}"
REQUIRE_VERIBLE_FORMAT="${REQUIRE_VERIBLE_FORMAT:-1}"

mkdir -p "$(dirname "${REPORT_PATH}")"
exec > >(tee "${REPORT_PATH}") 2>&1

echo "=== auto_tool_install ==="
echo "time: $(date -Is 2>/dev/null || date)"
echo "host: $(hostname 2>/dev/null || echo unknown)"
echo "root: ${ROOT_DIR}"
echo "report: ${REPORT_PATH}"
echo

echo "--- system ---"
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
ARCH_NAME="$(uname -m 2>/dev/null || echo unknown)"
echo "os: ${OS_NAME}"
echo "arch: ${ARCH_NAME}"
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "distro: ${PRETTY_NAME:-${NAME:-unknown}}"
fi
echo

PKG_MGR=""
PKG_UPDATE_CMD=()
PKG_INSTALL_CMD=()
if command -v apt-get >/dev/null 2>&1; then
  PKG_MGR="apt"
  PKG_UPDATE_CMD=(apt-get update -y)
  PKG_INSTALL_CMD=(apt-get install -y)
elif command -v dnf >/dev/null 2>&1; then
  PKG_MGR="dnf"
  PKG_INSTALL_CMD=(dnf install -y)
elif command -v yum >/dev/null 2>&1; then
  PKG_MGR="yum"
  PKG_INSTALL_CMD=(yum install -y)
elif command -v pacman >/dev/null 2>&1; then
  PKG_MGR="pacman"
  PKG_INSTALL_CMD=(pacman -S --noconfirm)
elif command -v zypper >/dev/null 2>&1; then
  PKG_MGR="zypper"
  PKG_INSTALL_CMD=(zypper --non-interactive install)
elif command -v apk >/dev/null 2>&1; then
  PKG_MGR="apk"
  PKG_INSTALL_CMD=(apk add)
elif command -v brew >/dev/null 2>&1; then
  PKG_MGR="brew"
  PKG_INSTALL_CMD=(brew install)
fi

echo "--- package manager ---"
if [[ -n "${PKG_MGR}" ]]; then
  echo "manager: ${PKG_MGR}"
else
  echo "manager: <none>"
fi
echo

PKG_UPDATED=0
MISSING_ITEMS=()
INSTALLED_ITEMS=()
FAILED_ITEMS=()
SKIPPED_ITEMS=()
REQUIRED_MISSING=()

need_root() {
  [[ "$(id -u)" -ne 0 ]]
}

have_sudo() {
  command -v sudo >/dev/null 2>&1
}

run_root() {
  if [[ "${PKG_MGR:-}" == "brew" ]]; then
    "$@"
  elif need_root && have_sudo; then
    sudo "$@"
  else
    "$@"
  fi
}

pkg_install() {
  if [[ -z "${PKG_MGR}" ]]; then
    return 1
  fi
  if need_root && ! have_sudo && [[ "${PKG_MGR}" != "brew" ]]; then
    return 1
  fi
  if [[ "${PKG_UPDATED}" -eq 0 && "${#PKG_UPDATE_CMD[@]}" -gt 0 ]]; then
    echo "+ ${PKG_UPDATE_CMD[*]}"
    if ! run_root "${PKG_UPDATE_CMD[@]}"; then
      echo "[WARN] package index update failed"
    fi
    PKG_UPDATED=1
  fi
  echo "+ ${PKG_INSTALL_CMD[*]} $*"
  run_root "${PKG_INSTALL_CMD[@]}" "$@"
}

pkg_for_cmd() {
  local cmd="$1"
  case "${PKG_MGR}" in
    apt)
      case "${cmd}" in
        docker) echo "docker.io" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3) echo "python3" ;;
        pip3) echo "python3-pip" ;;
        gcc) echo "gcc" ;;
        g++) echo "g++" ;;
        pkg-config) echo "pkg-config" ;;
        curl) echo "curl" ;;
        tar) echo "tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "nodejs npm" ;;
      esac
      ;;
    dnf|yum)
      case "${cmd}" in
        docker) echo "docker" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3) echo "python3" ;;
        pip3) echo "python3-pip" ;;
        gcc) echo "gcc" ;;
        g++) echo "gcc-c++" ;;
        pkg-config) echo "pkgconf-pkg-config" ;;
        curl) echo "curl" ;;
        tar) echo "tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "nodejs npm" ;;
      esac
      ;;
    pacman)
      case "${cmd}" in
        docker) echo "docker" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3) echo "python" ;;
        pip3) echo "python-pip" ;;
        gcc|g++) echo "gcc" ;;
        pkg-config) echo "pkgconf" ;;
        curl) echo "curl" ;;
        tar) echo "tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "nodejs npm" ;;
      esac
      ;;
    zypper)
      case "${cmd}" in
        docker) echo "docker" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3) echo "python3" ;;
        pip3) echo "python3-pip" ;;
        gcc) echo "gcc" ;;
        g++) echo "gcc-c++" ;;
        pkg-config) echo "pkg-config" ;;
        curl) echo "curl" ;;
        tar) echo "tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "nodejs npm" ;;
      esac
      ;;
    apk)
      case "${cmd}" in
        docker) echo "docker" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3) echo "python3" ;;
        pip3) echo "py3-pip" ;;
        gcc|g++) echo "build-base" ;;
        pkg-config) echo "pkgconf" ;;
        curl) echo "curl" ;;
        tar) echo "tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "nodejs npm" ;;
      esac
      ;;
    brew)
      case "${cmd}" in
        docker) echo "docker" ;;
        make) echo "make" ;;
        git) echo "git" ;;
        python3|pip3) echo "python" ;;
        gcc|g++) echo "gcc" ;;
        pkg-config) echo "pkg-config" ;;
        curl) echo "curl" ;;
        tar) echo "gnu-tar" ;;
        verilator|verilator_coverage) echo "verilator" ;;
        gtkwave) echo "gtkwave" ;;
        lcov|genhtml) echo "lcov" ;;
        verible-*) echo "verible" ;;
        node|npm) echo "node" ;;
      esac
      ;;
  esac
}

check_cmd() {
  local cmd="$1"
  local label="${2:-$1}"
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "[OK] ${label}: $(command -v "${cmd}")"
    return 0
  fi
  echo "[MISS] ${label}: not found"
  return 1
}

ensure_cmd() {
  local cmd="$1"
  local label="${2:-$1}"
  if check_cmd "${cmd}" "${label}"; then
    return 0
  fi
  local pkgs_raw
  pkgs_raw="$(pkg_for_cmd "${cmd}")"
  if [[ -z "${pkgs_raw}" ]]; then
    echo "[SKIP] ${label}: no package mapping for ${PKG_MGR:-none}"
    SKIPPED_ITEMS+=("${label}")
    return 1
  fi
  read -r -a pkgs <<< "${pkgs_raw}"
  if pkg_install "${pkgs[@]}"; then
    if check_cmd "${cmd}" "${label}"; then
      INSTALLED_ITEMS+=("${label}")
      return 0
    fi
  fi
  FAILED_ITEMS+=("${label}")
  return 1
}

AI_TOOL_CMDS=(claude codex gemini opencode)
AI_TOOL_LABELS=("claude code" "codex" "gemini" "opencode")
AI_TOOL_NPM_PACKAGES=("@anthropic-ai/claude-code" "@openai/codex" "@google/gemini-cli" "opencode-ai")

ensure_docker() {
  if check_cmd docker "docker"; then
    return 0
  fi
  local pkgs_raw
  if [[ -n "${DOCKER_PKG:-}" ]]; then
    pkgs_raw="${DOCKER_PKG}"
  else
    pkgs_raw="$(pkg_for_cmd docker)"
  fi
  if [[ -z "${pkgs_raw}" ]]; then
    echo "[SKIP] docker: no package mapping for ${PKG_MGR:-none}"
    SKIPPED_ITEMS+=("docker")
    return 1
  fi
  read -r -a pkgs <<< "${pkgs_raw}"
  if pkg_install "${pkgs[@]}"; then
    if check_cmd docker "docker"; then
      INSTALLED_ITEMS+=("docker")
      return 0
    fi
  fi
  FAILED_ITEMS+=("docker")
  return 1
}

npm_global_install() {
  local args=("$@")
  if [[ -n "${NPM_REGISTRY:-}" ]]; then
    args=(--registry "${NPM_REGISTRY}" "${args[@]}")
  fi
  local prefix
  prefix="$(npm prefix -g 2>/dev/null || true)"
  case "${prefix}" in
    /usr|/usr/*|/usr/local|/usr/local/*)
      if need_root && have_sudo; then
        sudo npm install -g "${args[@]}"
      else
        npm install -g "${args[@]}"
      fi
      ;;
    *)
      npm install -g "${args[@]}"
      ;;
  esac
}

check_ai_tools_host() {
  local missing_idx=()
  local i
  for i in "${!AI_TOOL_CMDS[@]}"; do
    if ! check_cmd "${AI_TOOL_CMDS[$i]}" "${AI_TOOL_LABELS[$i]}"; then
      missing_idx+=("${i}")
    fi
  done

  if [[ "${#missing_idx[@]}" -gt 0 ]]; then
    if [[ "${ALLOW_NPM_INSTALL:-1}" == "1" ]]; then
      ensure_cmd node
      ensure_cmd npm
      if command -v npm >/dev/null 2>&1; then
        local pkgs=()
        for i in "${missing_idx[@]}"; do
          pkgs+=("${AI_TOOL_NPM_PACKAGES[$i]}")
        done
        echo "[INFO] installing AI tools via npm: ${pkgs[*]}"
        if npm_global_install "${pkgs[@]}"; then
          INSTALLED_ITEMS+=("ai_tools_host")
        else
          FAILED_ITEMS+=("ai_tools_host")
        fi
      else
        echo "[SKIP] AI tools install: npm not available"
        SKIPPED_ITEMS+=("ai_tools_host")
      fi
    else
      echo "[SKIP] AI tools install: ALLOW_NPM_INSTALL=0"
      SKIPPED_ITEMS+=("ai_tools_host")
    fi
  fi

  if [[ "${#missing_idx[@]}" -gt 0 ]]; then
    for i in "${missing_idx[@]}"; do
      if ! check_cmd "${AI_TOOL_CMDS[$i]}" "${AI_TOOL_LABELS[$i]}"; then
        MISSING_ITEMS+=("${AI_TOOL_LABELS[$i]}")
      fi
    done
  fi
}

build_ai_tools_image() {
  local image="${AI_TOOLS_DOCKER_IMAGE:-verilog_sim_ai_tools:latest}"
  local base="${AI_TOOLS_DOCKER_BASE_IMAGE:-node:20-bullseye-slim}"
  if [[ "${DOCKER_BUILD_AI_TOOLS:-1}" != "1" ]]; then
    echo "[SKIP] docker AI tools image build: DOCKER_BUILD_AI_TOOLS=0"
    SKIPPED_ITEMS+=("docker_ai_tools_image")
    return 1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "[SKIP] docker AI tools image build: docker not available"
    SKIPPED_ITEMS+=("docker_ai_tools_image")
    return 1
  fi

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  cat > "${tmp_dir}/Dockerfile" <<EOF
FROM ${base}
ARG NPM_REGISTRY
RUN if [ -n "\${NPM_REGISTRY}" ]; then npm config set registry "\${NPM_REGISTRY}"; fi \\
 && npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli opencode-ai \\
 && npm cache clean --force
EOF

  local build_args=()
  if [[ -n "${NPM_REGISTRY:-}" ]]; then
    build_args+=(--build-arg "NPM_REGISTRY=${NPM_REGISTRY}")
  fi
  echo "+ docker build -t ${image} ${build_args[*]} ${tmp_dir}"
  if docker build -t "${image}" "${build_args[@]}" "${tmp_dir}"; then
    echo "[OK] docker image built: ${image}"
    INSTALLED_ITEMS+=("docker_ai_tools_image")
    rm -rf "${tmp_dir}"
    return 0
  fi
  rm -rf "${tmp_dir}"
  FAILED_ITEMS+=("docker_ai_tools_image")
  return 1
}

check_ai_tools_docker() {
  local image="${AI_TOOLS_DOCKER_IMAGE:-verilog_sim_ai_tools:latest}"
  if ! command -v docker >/dev/null 2>&1; then
    echo "[SKIP] docker AI tools: docker not available"
    SKIPPED_ITEMS+=("docker_ai_tools")
    return 1
  fi
  if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "[SKIP] docker AI tools: image not found (${image})"
    SKIPPED_ITEMS+=("docker_ai_tools")
    return 1
  fi
  local i
  for i in "${!AI_TOOL_CMDS[@]}"; do
    if docker run --rm "${image}" "${AI_TOOL_CMDS[$i]}" --version >/dev/null 2>&1; then
      echo "[OK] docker ${AI_TOOL_LABELS[$i]}: installed"
    elif docker run --rm "${image}" "${AI_TOOL_CMDS[$i]}" --help >/dev/null 2>&1; then
      echo "[OK] docker ${AI_TOOL_LABELS[$i]}: installed"
    else
      echo "[WARN] docker ${AI_TOOL_LABELS[$i]}: not available"
      MISSING_ITEMS+=("docker_${AI_TOOL_LABELS[$i]}")
    fi
  done
}

echo "--- core tools ---"
ensure_cmd make
ensure_cmd git
ensure_cmd gcc
ensure_cmd g++
ensure_cmd pkg-config
ensure_cmd python3
echo

echo "--- docker engine ---"
DOCKER_OK=0
if ensure_docker; then
  if docker info >/dev/null 2>&1; then
    DOCKER_OK=1
  else
    echo "[WARN] docker installed but daemon not accessible"
  fi
fi
if [[ "${REQUIRE_DOCKER}" == "1" && "${DOCKER_OK}" -ne 1 ]]; then
  REQUIRED_MISSING+=("docker")
fi
echo

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" && -x "${ROOT_DIR}/tools/python312/bin/python3.12" ]]; then
  PYTHON_BIN="${ROOT_DIR}/tools/python312/bin/python3.12"
  echo "[INFO] using local python: ${PYTHON_BIN}"
fi
if [[ -z "${PYTHON_BIN}" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  fi
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "[ERROR] python not found after install attempt"
else
  echo "--- python ---"
  "${PYTHON_BIN}" --version || true
  PY_VER="$("${PYTHON_BIN}" - <<'PY' 2>/dev/null || true
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
)"
  if [[ -n "${PY_VER}" ]]; then
    echo "python_version: ${PY_VER}"
  fi
  PY_MINOR="$("${PYTHON_BIN}" - <<'PY' 2>/dev/null || true
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  if [[ -n "${PY_MINOR}" ]]; then
    echo "python_minor: ${PY_MINOR}"
  fi
  echo
fi

ensure_pip() {
  if [[ -z "${PYTHON_BIN}" ]]; then
    return 1
  fi
  if "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
    echo "[OK] pip: $("${PYTHON_BIN}" -m pip --version 2>/dev/null)"
    return 0
  fi
  echo "[MISS] pip: not found"
  if "${PYTHON_BIN}" -m ensurepip --upgrade >/dev/null 2>&1; then
    echo "[OK] pip: installed via ensurepip"
  else
    local pkgs_raw
    pkgs_raw="$(pkg_for_cmd pip3)"
    if [[ -z "${pkgs_raw}" ]]; then
      echo "[SKIP] pip: no package mapping for ${PKG_MGR:-none}"
      SKIPPED_ITEMS+=("pip")
      return 1
    fi
    read -r -a pkgs <<< "${pkgs_raw}"
    if ! pkg_install "${pkgs[@]}"; then
      FAILED_ITEMS+=("pip")
      return 1
    fi
  fi
  if "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
    echo "[OK] pip: $("${PYTHON_BIN}" -m pip --version 2>/dev/null)"
    INSTALLED_ITEMS+=("pip")
    return 0
  fi
  FAILED_ITEMS+=("pip")
  return 1
}

echo "--- pip ---"
ensure_pip || true
echo

python_in_venv() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import sys
in_venv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix
sys.exit(0 if in_venv else 1)
PY
}

pip_install() {
  local args=("$@")
  local user_flag=()
  if ! python_in_venv && [[ "$(id -u)" -ne 0 ]]; then
    user_flag=(--user)
  fi
  "${PYTHON_BIN}" -m pip install "${user_flag[@]}" "${args[@]}"
}

pip_install_prefer_wheelhouse() {
  local wheelhouse_dir="$1"
  local py_minor="$2"
  shift 2
  local pkgs=("$@")
  local tried_offline=0

  if [[ -d "${wheelhouse_dir}" ]]; then
    if [[ "${py_minor}" == "3.12" ]]; then
      echo "[INFO] prefer wheelhouse: ${wheelhouse_dir}"
      tried_offline=1
      if pip_install --no-index --find-links "${wheelhouse_dir}" "${pkgs[@]}"; then
        return 0
      fi
      echo "[WARN] wheelhouse install failed"
    else
      echo "[WARN] wheelhouse is cp312; python is ${py_minor}, skip offline install"
    fi
  else
    echo "[WARN] wheelhouse not found: ${wheelhouse_dir}"
  fi

  if [[ "${ALLOW_NETWORK_INSTALL:-0}" == "1" ]]; then
    pip_install "${pkgs[@]}"
    return $?
  fi

  if [[ "${tried_offline}" -eq 1 ]]; then
    echo "[SKIP] python packages: wheelhouse failed and network install disabled"
  else
    echo "[SKIP] python packages: set ALLOW_NETWORK_INSTALL=1 to use online pip"
  fi
  SKIPPED_ITEMS+=("python_packages")
  return 1
}

check_py_pkg() {
  local module="$1"
  local dist="$2"
  local want="$3"
  local version
  if ! version="$("${PYTHON_BIN}" - <<'PY' "${module}" "${dist}" 2>/dev/null
import importlib.util
import sys
from importlib.metadata import PackageNotFoundError, version
mod = sys.argv[1]
dist = sys.argv[2]
if importlib.util.find_spec(mod) is None:
    sys.exit(2)
try:
    print(version(dist))
except PackageNotFoundError:
    print("unknown")
PY
)"; then
    echo "[MISS] python package ${dist}: not installed"
    return 1
  fi
  echo "[OK] python package ${dist}: ${version}"
  if [[ -n "${want}" && "${version}" != "${want}" ]]; then
    echo "[WARN] ${dist} version ${version} != ${want} (kept existing)"
  fi
  return 0
}

echo "--- python packages ---"
if [[ -n "${PYTHON_BIN}" ]]; then
  WHEELHOUSE_DIR="${WHEELHOUSE_DIR:-${ROOT_DIR}/cocotb_offline/wheels_p12}"
  if [[ -z "${PY_MINOR:-}" ]]; then
    PY_MINOR="$("${PYTHON_BIN}" - <<'PY' 2>/dev/null || true
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  fi
  REQUIRED_PY_PKGS=(
    "cocotb:cocotb:2.0.1"
    "cocotb_bus:cocotb-bus:0.3.0"
    "cocotb_coverage:cocotb-coverage:2.0"
    "pytest:pytest:9.0.2"
  )
  MISSING_PY_PKGS=()
  for entry in "${REQUIRED_PY_PKGS[@]}"; do
    IFS=":" read -r mod dist want <<< "${entry}"
    if ! check_py_pkg "${mod}" "${dist}" "${want}"; then
      MISSING_PY_PKGS+=("${dist}==${want}")
    fi
  done

  if [[ "${#MISSING_PY_PKGS[@]}" -gt 0 ]]; then
    echo "[INFO] installing missing python packages: ${MISSING_PY_PKGS[*]}"
    if ! pip_install_prefer_wheelhouse "${WHEELHOUSE_DIR}" "${PY_MINOR:-}" "${MISSING_PY_PKGS[@]}"; then
      FAILED_ITEMS+=("python_packages")
    fi
  fi

  echo
  for entry in "${REQUIRED_PY_PKGS[@]}"; do
    IFS=":" read -r mod dist want <<< "${entry}"
    check_py_pkg "${mod}" "${dist}" "${want}" || MISSING_ITEMS+=("${dist}")
  done
  "${PYTHON_BIN}" -m pip check || true
else
  echo "[SKIP] python packages: python not available"
  SKIPPED_ITEMS+=("python_packages")
fi
echo

echo "--- AI CLI tools (host) ---"
check_ai_tools_host
echo

echo "--- AI CLI tools (docker) ---"
if command -v docker >/dev/null 2>&1; then
  build_ai_tools_image || true
  check_ai_tools_docker || true
else
  echo "[SKIP] docker AI tools: docker not available"
  SKIPPED_ITEMS+=("docker_ai_tools")
fi
echo

echo "--- sim and lint tools ---"
ensure_cmd verilator
ensure_cmd verilator_coverage
ensure_cmd lcov
ensure_cmd genhtml
ensure_cmd gtkwave

VERIBLE_MISSING=0
VERIBLE_FORMAT_OK=0
if check_cmd verible-verilog-format "verible format"; then
  VERIBLE_FORMAT_OK=1
else
  VERIBLE_MISSING=1
fi
if ! check_cmd verible-verilog-lint "verible lint"; then
  VERIBLE_MISSING=1
fi
if ! check_cmd verible-verilog-syntax "verible syntax"; then
  VERIBLE_MISSING=1
fi
if [[ "${VERIBLE_MISSING}" -eq 1 ]]; then
  ensure_cmd verible-verilog-format "verible (package)"
fi
if [[ "${VERIBLE_FORMAT_OK}" -ne 1 && -x "$(command -v verible-verilog-format 2>/dev/null)" ]]; then
  VERIBLE_FORMAT_OK=1
fi
if [[ "${REQUIRE_VERIBLE_FORMAT}" == "1" && "${VERIBLE_FORMAT_OK}" -ne 1 ]]; then
  REQUIRED_MISSING+=("verible-verilog-format")
fi
echo

echo "--- optional tools ---"
check_cmd vcs "vcs (licensed)" || true
check_cmd verdi "verdi (licensed)" || true
echo

echo "--- env ---"
for v in DISPLAY SNPSLMD_LICENSE_FILE LM_LICENSE_FILE; do
  if [[ -n "${!v-}" ]]; then
    echo "${v}=${!v}"
  else
    echo "${v}=<unset>"
  fi
done
echo

echo "--- summary ---"
if [[ "${#INSTALLED_ITEMS[@]}" -gt 0 ]]; then
  echo "installed: ${INSTALLED_ITEMS[*]}"
fi
if [[ "${#FAILED_ITEMS[@]}" -gt 0 ]]; then
  echo "failed: ${FAILED_ITEMS[*]}"
fi
if [[ "${#SKIPPED_ITEMS[@]}" -gt 0 ]]; then
  echo "skipped: ${SKIPPED_ITEMS[*]}"
fi
if [[ "${#MISSING_ITEMS[@]}" -gt 0 ]]; then
  echo "missing: ${MISSING_ITEMS[*]}"
fi
if [[ "${#REQUIRED_MISSING[@]}" -gt 0 ]]; then
  echo "required_missing: ${REQUIRED_MISSING[*]}"
  echo "status: failed (required tools missing)"
else
  echo "status: ok"
fi
echo "report: ${REPORT_PATH}"
echo "done."
if [[ "${#REQUIRED_MISSING[@]}" -gt 0 ]]; then
  exit 2
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEST_DIR="${ROOT_DIR}/tests"
PYTHON_BIN="${PYTHON_BIN:-python3}"

OUT="${DOCTOR_OUT:-}"
if [[ -n "${OUT}" ]]; then
  mkdir -p "$(dirname "${OUT}")"
  exec > >(tee "${OUT}") 2>&1
fi

echo "=== cocotb_vcs doctor ==="
echo "time: $(date -Is 2>/dev/null || date)"
echo "host: $(hostname 2>/dev/null || echo unknown)"
echo "pwd : $(pwd)"
echo "root: ${ROOT_DIR}"
echo

echo "--- tools ---"
echo "PYTHON_BIN=${PYTHON_BIN}"
if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "python: $(command -v "${PYTHON_BIN}")"
elif [[ -x "${PYTHON_BIN}" ]]; then
  echo "python: ${PYTHON_BIN}"
else
  echo "python: <not found>"
fi
for t in python3 make vcs verdi urg; do
  if command -v "${t}" >/dev/null 2>&1; then
    echo "${t}: $(command -v "${t}")"
  else
    echo "${t}: <not found>"
  fi
done
if command -v gcc >/dev/null 2>&1; then
  gcc_path="$(command -v gcc)"
  echo "gcc: ${gcc_path}"
  echo "gcc_version: $(gcc --version 2>/dev/null | head -n 1 || true)"
  expected="/tools/hydora64/hdk-r7-9.2.0/22.10"
  if [[ "${gcc_path}" != "${expected}"* ]]; then
    echo "[WARN] gcc is not under expected prefix: ${expected}"
    echo "       Hint: source ${ROOT_DIR}/cfg_env.csh"
    echo "             or (csh/tcsh): setenv PATH ${expected}/bin:\\$PATH"
  fi
else
  echo "gcc: <not found>"
fi
echo

echo "--- env ---"
for v in VERDI_HOME NOVAS_HOME VCS_HOME VCS_BIN_DIR SNPSLMD_LICENSE_FILE LM_LICENSE_FILE; do
  if [[ -n "${!v-}" ]]; then
    echo "${v}=${!v}"
  else
    echo "${v}=<unset>"
  fi
done
echo "LANG=${LANG-<unset>}"
echo "LC_ALL=${LC_ALL-<unset>}"
echo "LC_CTYPE=${LC_CTYPE-<unset>}"
echo

echo "--- python/cocotb ---"
"${PYTHON_BIN}" --version || true
"${PYTHON_BIN}" - <<'PY' || true
import locale
import sys
import sysconfig

print(f"sys.executable={sys.executable}")
print(f"sys.version={sys.version.splitlines()[0]}")
print(f"sys.prefix={sys.prefix}")
print(f"sys.base_prefix={getattr(sys, 'base_prefix', '')}")
print(f"sys.exec_prefix={sys.exec_prefix}")
print(f"stdlib={sysconfig.get_path('stdlib')}")
print(f"platstdlib={sysconfig.get_path('platstdlib')}")
try:
    import encodings

    print(f"encodings={encodings.__file__}")
except Exception as exc:
    print(f"[ERROR] import encodings failed: {exc!r}")
print(f"preferredencoding={locale.getpreferredencoding(False)}")
PY

cocotb_config=()
if "${PYTHON_BIN}" -m cocotb_tools.config --version >/dev/null 2>&1; then
  cocotb_config=("${PYTHON_BIN}" -m cocotb_tools.config)
elif "${PYTHON_BIN}" -m cocotb.config --version >/dev/null 2>&1; then
  cocotb_config=("${PYTHON_BIN}" -m cocotb.config)
fi

if [[ "${#cocotb_config[@]}" -ne 0 ]]; then
  "${cocotb_config[@]}" --version || true
  "${cocotb_config[@]}" --python-bin || true
  "${cocotb_config[@]}" --libpython || true
  "${cocotb_config[@]}" --lib-name-path vpi vcs || true
else
  echo "[WARN] cocotb not found for PYTHON_BIN=${PYTHON_BIN}"
fi
echo

TOPLEVEL="${TOPLEVEL:-tb_top}"
COCOTB_TEST_MODULES="${COCOTB_TEST_MODULES:-${MODULE:-tests.test_adder}}"
COCOTB_TESTCASE="${COCOTB_TESTCASE:-${TESTCASE:-}}"
RTL_FILELISTS="${RTL_FILELISTS:-${ROOT_DIR}/filelists/rtl.f}"
TB_SOURCES="${TB_SOURCES:-${ROOT_DIR}/tb/hdl/${TOPLEVEL}.sv}"
WAVES="${WAVES:-1}"
DEBUG="${DEBUG:-1}"
COV="${COV:-1}"

echo "--- config ---"
echo "TOPLEVEL=${TOPLEVEL}"
echo "COCOTB_TEST_MODULES=${COCOTB_TEST_MODULES}"
echo "COCOTB_TESTCASE=${COCOTB_TESTCASE:-<unset>}"
echo "RTL_FILELISTS=${RTL_FILELISTS}"
echo "TB_SOURCES=${TB_SOURCES}"
echo "WAVES=${WAVES} DEBUG=${DEBUG} COV=${COV}"
echo

echo "--- file checks ---"
if [[ ! -f "${TB_SOURCES}" ]]; then
  echo "[ERROR] TB_SOURCES not found: ${TB_SOURCES}"
  echo "Hint: set TOPLEVEL=... or TB_SOURCES=..."
  exit 2
fi
echo "[OK] TB_SOURCES exists"

missing_fl=0
for fl in ${RTL_FILELISTS}; do
  if [[ ! -f "${fl}" ]]; then
    echo "[ERROR] RTL filelist not found: ${fl}"
    missing_fl=1
  fi
done
if [[ "${missing_fl}" == "1" ]]; then
  exit 2
fi
echo "[OK] RTL_FILELISTS exist"
echo

echo "--- filelist expansion ---"
EXPAND="${SCRIPT_DIR}/expand_filelists.py"
if [[ ! -f "${EXPAND}" ]]; then
  echo "[ERROR] missing ${EXPAND}"
  exit 2
fi

srcs="$("${PYTHON_BIN}" "${EXPAND}" --sources ${RTL_FILELISTS} || true)"
args="$("${PYTHON_BIN}" "${EXPAND}" --args ${RTL_FILELISTS} || true)"
echo "sources_count: $(wc -w <<<"${srcs}" | tr -d ' ')"
echo "args: ${args}"

missing_src=0
for s in ${srcs}; do
  if [[ "${s}" == \$* || "${s}" == "~"* ]]; then
    continue
  fi
  if [[ ! -f "${s}" ]]; then
    echo "[MISSING] ${s}"
    missing_src=1
  fi
done
if [[ "${missing_src}" == "1" ]]; then
  echo "[ERROR] Missing source files found. Fix filelists/paths before running VCS."
  exit 2
fi
echo "[OK] Expanded sources exist"
echo

echo "--- verdi/fsdb ---"
if [[ "${WAVES}" == "1" ]]; then
  if [[ -z "${VERDI_HOME:-}" && -n "$(command -v verdi 2>/dev/null || true)" ]]; then
    autod="$(dirname "$(dirname "$(command -v verdi)")")"
    echo "VERDI_HOME autodetect: ${autod}"
  fi

  tab_candidates=()
  if [[ -n "${VERDI_PLI_TAB:-}" ]]; then
    tab_candidates+=("${VERDI_PLI_TAB}")
  fi
  if [[ -n "${VERDI_HOME:-}" ]]; then
    while IFS= read -r -d '' f; do tab_candidates+=("$f"); done < <(find "${VERDI_HOME}/share/PLI/VCS" -maxdepth 2 -name "verdi.tab" -print0 2>/dev/null || true)
    while IFS= read -r -d '' f; do tab_candidates+=("$f"); done < <(find "${VERDI_HOME}/share/PLI/VCS" -maxdepth 2 -name "novas.tab" -print0 2>/dev/null || true)
  fi

  found_tab=""
  for f in "${tab_candidates[@]}"; do
    if [[ -f "${f}" ]]; then
      found_tab="${f}"
      break
    fi
  done

  if [[ -n "${found_tab}" ]]; then
    echo "[OK] PLI tab: ${found_tab}"
    dir="$(dirname "${found_tab}")"
    pli_lib=""
    if [[ -n "${VERDI_PLI_LIB:-}" && -f "${VERDI_PLI_LIB}" ]]; then
      pli_lib="${VERDI_PLI_LIB}"
    elif [[ -f "${dir}/pli.a" ]]; then
      pli_lib="${dir}/pli.a"
    elif [[ -f "${dir}/pli.so" ]]; then
      pli_lib="${dir}/pli.so"
    fi

    if [[ -n "${pli_lib}" ]]; then
      echo "[OK] PLI lib: ${pli_lib}"
    else
      echo "[WARN] Cannot locate pli.a/pli.so near PLI tab."
      echo "       Hint: set VERDI_PLI_LIB=/path/to/pli.a (or pli.so), or run with WAVES=0"
    fi
  else
    echo "[WARN] WAVES=1 but cannot locate verdi.tab/novas.tab."
    echo "       Hint: set VERDI_HOME, or run with WAVES=0, or set VERDI_PLI_TAB=/path/to/verdi.tab"
  fi

  if ! command -v verdi >/dev/null 2>&1; then
    echo "[WARN] verdi not found in PATH (only affects 'make verdi' and auto-detect)."
  else
    echo "[OK] verdi in PATH"
  fi
else
  echo "WAVES=0 -> skip FSDB checks"
fi
echo

echo "--- regression discovery ---"
if [[ -d "${TEST_DIR}" ]]; then
  n=$(ls -1 "${TEST_DIR}"/test_*.py 2>/dev/null | wc -l | tr -d ' ')
  echo "tests/test_*.py: ${n}"
fi
echo

echo "--- summary ---"
if ! command -v vcs >/dev/null 2>&1; then
  echo "[ERROR] vcs not found in PATH."
  echo "Hint: source VCS setup script / load module / check PATH, then rerun: make doctor"
  exit 2
fi
echo "[OK] Basic preflight passed."

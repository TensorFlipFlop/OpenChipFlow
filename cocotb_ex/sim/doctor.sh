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

echo "=== cocotb_ex doctor (verilator) ==="
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
for t in python3 make verilator verilator_coverage lcov genhtml gtkwave; do
  if command -v "${t}" >/dev/null 2>&1; then
    echo "${t}: $(command -v "${t}")"
  else
    echo "${t}: <not found>"
  fi
done
echo

echo "--- env ---"
for v in DISPLAY SNPSLMD_LICENSE_FILE LM_LICENSE_FILE; do
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
  "${cocotb_config[@]}" --lib-dir || true
  lib_dir="$("${cocotb_config[@]}" --lib-dir 2>/dev/null || true)"
  if [[ -n "${lib_dir}" ]]; then
    if [[ -f "${lib_dir}/libcocotbvpi_verilator.so" ]]; then
      echo "libcocotbvpi_verilator.so: ${lib_dir}/libcocotbvpi_verilator.so"
    else
      echo "[WARN] libcocotbvpi_verilator.so not found under: ${lib_dir}"
    fi
  fi
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
WAVE_SCOPE="${WAVE_SCOPE:-full}"
WAVE_FILE="${WAVE_FILE:-}"
DEBUG="${DEBUG:-0}"
COV="${COV:-1}"
COV_DAT_FILE="${COV_DAT_FILE:-}"

echo "--- config ---"
echo "TOPLEVEL=${TOPLEVEL}"
echo "COCOTB_TEST_MODULES=${COCOTB_TEST_MODULES}"
echo "COCOTB_TESTCASE=${COCOTB_TESTCASE:-<unset>}"
echo "RTL_FILELISTS=${RTL_FILELISTS}"
echo "TB_SOURCES=${TB_SOURCES}"
echo "WAVES=${WAVES} WAVE_SCOPE=${WAVE_SCOPE} WAVE_FILE=${WAVE_FILE:-<auto>}"
echo "DEBUG=${DEBUG} COV=${COV} COV_DAT_FILE=${COV_DAT_FILE:-<auto>}"
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
  echo "[ERROR] Missing source files found. Fix filelists/paths before running Verilator."
  exit 2
fi
echo "[OK] Expanded sources exist"
echo

echo "--- waves ---"
if [[ "${WAVES}" == "1" ]]; then
  if [[ -z "${WAVE_FILE}" ]]; then
    echo "WAVE_FILE: <auto by Makefile>"
  else
    echo "WAVE_FILE: ${WAVE_FILE}"
  fi
  if [[ -z "${DISPLAY-}" ]]; then
    echo "[WARN] DISPLAY is unset; gtkwave cannot open GUI in headless sessions."
  fi
else
  echo "WAVES=0 -> skip trace checks"
fi
echo

echo "--- coverage ---"
if [[ "${COV}" == "1" ]]; then
  command -v verilator_coverage >/dev/null 2>&1 || echo "[WARN] verilator_coverage not found (make cov will fail)."
  command -v genhtml >/dev/null 2>&1 || echo "[WARN] genhtml not found (make cov will fail)."
  if [[ -n "${COV_DAT_FILE}" ]]; then
    echo "COV_DAT_FILE: ${COV_DAT_FILE}"
  else
    echo "COV_DAT_FILE: <auto by Makefile>"
  fi
else
  echo "COV=0 -> skip coverage checks"
fi
echo

echo "--- regression discovery ---"
if [[ -d "${TEST_DIR}" ]]; then
  n=$(ls -1 "${TEST_DIR}"/test_*.py 2>/dev/null | wc -l | tr -d ' ')
  echo "tests/test_*.py: ${n}"
fi
echo

echo "--- summary ---"
if ! command -v verilator >/dev/null 2>&1; then
  echo "[ERROR] verilator not found in PATH."
  echo "Hint: install verilator and ensure it is in PATH, then rerun: make doctor"
  exit 2
fi
echo "[OK] Basic preflight passed."

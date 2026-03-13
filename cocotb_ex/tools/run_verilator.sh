#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SIM_DIR="${ROOT_DIR}/cocotb_ex/sim"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/cocotb_ex/artifacts/logs}"
mkdir -p "${LOG_DIR}"

LOG_FILE="${LOG_FILE:-${LOG_DIR}/verilator_build.log}"
COMPILE_LOG="${COMPILE_LOG:-${LOG_DIR}/verilator_compile.log}"
TARGET="${TARGET:-sim}"

if [[ ! -d "${SIM_DIR}" ]]; then
  echo "[run_verilator] ERROR: sim directory not found: ${SIM_DIR}" | tee "${LOG_FILE}"
  exit 1
fi

append_arg() {
  local name="$1"
  local value="${!name:-}"
  if [[ -n "${value}" ]]; then
    MAKE_ARGS+=("${name}=${value}")
  fi
}

if [[ -z "${SIM_LOG:-}" ]]; then
  SIM_LOG="${LOG_FILE}"
fi

MAKE_ARGS=("${TARGET}" "SIM_LOG=${SIM_LOG}" "COMPILE_LOG=${COMPILE_LOG}")
append_arg TOPLEVEL
append_arg RTL_FILELISTS
append_arg TB_SOURCES
append_arg COCOTB_TEST_MODULES
append_arg COCOTB_TESTCASE
append_arg COCOTB_PLUSARGS
append_arg CASE
append_arg SEED
append_arg OUT_ROOT
append_arg WAVES
append_arg WAVE_SCOPE
append_arg COV
append_arg PYTHON_BIN
append_arg PYTHON3
append_arg DEBUG

echo "[run_verilator] make ${MAKE_ARGS[*]}" | tee "${LOG_FILE}"
"${SIM_DIR}/run_make.sh" "${MAKE_ARGS[@]}" 2>&1 | tee -a "${LOG_FILE}"

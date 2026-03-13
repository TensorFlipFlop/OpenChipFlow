#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SIM_DIR="${ROOT_DIR}/cocotb_ex/sim"
LOG_DIR="${LOG_DIR:-${ROOT_DIR}/cocotb_ex/artifacts/logs}"
mkdir -p "${LOG_DIR}"

TARGET="${TARGET:-sim}"

sanitize() {
  echo "$1" | tr ' /:' '___'
}

log_basename="cocotb_sim.log"
if [[ -n "${CASE:-}" || -n "${SEED:-}" ]]; then
  case_tag="case"
  seed_tag="seed"
  if [[ -n "${CASE:-}" ]]; then
    case_tag="$(sanitize "${CASE}")"
  fi
  if [[ -n "${SEED:-}" ]]; then
    seed_tag="seed$(sanitize "${SEED}")"
  fi
  log_basename="cocotb_${case_tag}_${seed_tag}.log"
fi

LOG_FILE="${LOG_FILE:-${SIM_LOG:-${LOG_DIR}/${log_basename}}}"
COMPILE_LOG="${COMPILE_LOG:-${LOG_DIR}/cocotb_compile.log}"

if [[ ! -d "${SIM_DIR}" ]]; then
  echo "[run_cocotb] ERROR: sim directory not found: ${SIM_DIR}" | tee "${LOG_FILE}"
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

if [[ -z "${COV:-}" ]]; then
  COV=0
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

echo "[run_cocotb] make ${MAKE_ARGS[*]}" | tee "${LOG_FILE}"
"${SIM_DIR}/run_make.sh" "${MAKE_ARGS[@]}" 2>&1 | tee -a "${LOG_FILE}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DERIVED_WORK_DIR=""
if DERIVED_WORK_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd 2>/dev/null)"; then
    :
fi

if [[ -n "${DERIVED_WORK_DIR}" && -d "${DERIVED_WORK_DIR}/sim" ]]; then
    WORK_DIR="${WORK_DIR:-${DERIVED_WORK_DIR}}"
else
    WORK_DIR="${WORK_DIR:-/work}"
fi

SIM_DIR="${WORK_DIR}/sim"
MAKE_BIN="${MAKE_BIN:-make}"

TOPLEVEL="${TOPLEVEL:-ai_tb_top}"
RTL_FILELISTS="${RTL_FILELISTS:-../artifacts/sessions/e2e_valid_130529/workspace/filelists/ai_dut.f}"
MODULE="${MODULE:-tests.test_ai}"
TESTCASE="${TESTCASE:-run_basic}"

REQ_TESTCASE="${REQ_TESTCASE:-test_input_ready_behavior}"
PACK_ORDER_MATRIX_TESTCASE="${PACK_ORDER_MATRIX_TESTCASE:-test_packing_both_orders}"

WAVES="${WAVES:-1}"
COV="${COV:-0}"
OUT_ROOT="${OUT_ROOT:-out/e2e_valid_130529}"

RUN_REQ003="${RUN_REQ003:-1}"
RUN_PACK_ORDER_MATRIX="${RUN_PACK_ORDER_MATRIX:-1}"
RUN_FULL_MODULE="${RUN_FULL_MODULE:-0}"

BASE_TOP_PARAMS="${TOP_PARAMS:-}"
if [[ -n "${BASE_TOP_PARAMS}" ]]; then
    DEFAULT_PACK_ORDER1_TOP_PARAMS="${BASE_TOP_PARAMS} -GPACK_ORDER=1"
else
    DEFAULT_PACK_ORDER1_TOP_PARAMS="-GPACK_ORDER=1"
fi
PACK_ORDER1_TOP_PARAMS="${PACK_ORDER1_TOP_PARAMS:-${DEFAULT_PACK_ORDER1_TOP_PARAMS}}"
FULL_MODULE_TOP_PARAMS="${FULL_MODULE_TOP_PARAMS:-${BASE_TOP_PARAMS}}"

if [[ ! -f "${SIM_DIR}/Makefile" ]]; then
    echo "ERROR: simulation makefile not found: ${SIM_DIR}/Makefile" >&2
    exit 1
fi

run_make() {
    local target="$1"
    shift
    "${MAKE_BIN}" -C "${SIM_DIR}" "${target}" "$@"
}

run_sim() {
    local run_tag="$1"
    local testcase="$2"
    local top_params="$3"
    local -a args=(
        "TOPLEVEL=${TOPLEVEL}"
        "RTL_FILELISTS=${RTL_FILELISTS}"
        "MODULE=${MODULE}"
        "WAVES=${WAVES}"
        "COV=${COV}"
        "OUT_ROOT=${OUT_ROOT}/${run_tag}"
    )

    if [[ -n "${testcase}" ]]; then
        args+=("TESTCASE=${testcase}")
    fi
    if [[ -n "${top_params}" ]]; then
        args+=("TOP_PARAMS=${top_params}")
    fi

    run_make sim "${args[@]}"
}

echo "WORK_DIR=${WORK_DIR}"

run_make doctor \
    "TOPLEVEL=${TOPLEVEL}" \
    "RTL_FILELISTS=${RTL_FILELISTS}" \
    "MODULE=${MODULE}" \
    "TESTCASE=${TESTCASE}" \
    "WAVES=${WAVES}" \
    "COV=${COV}"

run_sim "smoke" "${TESTCASE}" "${BASE_TOP_PARAMS}"

if [[ "${RUN_REQ003}" != "0" ]]; then
    run_sim "req003" "${REQ_TESTCASE}" "${BASE_TOP_PARAMS}"
fi

if [[ "${RUN_PACK_ORDER_MATRIX}" != "0" ]]; then
    run_sim "pack_order1" "${PACK_ORDER_MATRIX_TESTCASE}" "${PACK_ORDER1_TOP_PARAMS}"
fi

if [[ "${RUN_FULL_MODULE}" != "0" ]]; then
    run_sim "full_module" "" "${FULL_MODULE_TOP_PARAMS}"
fi

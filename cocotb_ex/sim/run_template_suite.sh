#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUT_DIR="${REGR_OUT:-${SCRIPT_DIR}/regression_out}"
mkdir -p "${OUT_DIR}"

SEEDS_STR="${REGR_SEEDS:-1 2}"
read -r -a seeds <<< "${SEEDS_STR}"
PYTHON_BIN="${PYTHON_BIN:-}"

extra_make=()
if [[ -n "${PYTHON_BIN}" ]]; then
  extra_make+=(PYTHON_BIN="${PYTHON_BIN}")
fi

echo "[suite] seeds: ${seeds[*]}"
echo "[suite] out  : ${OUT_DIR}"

DOCTOR_OUT="${OUT_DIR}/doctor.log" PYTHON_BIN="${PYTHON_BIN}" "${SCRIPT_DIR}/doctor.sh"

idx=0

run_one() {
  local toplevel="$1"
  local rtl_filelists="$2"
  local module="$3"
  local testcase="$4"
  local seed="$5"

  idx=$((idx + 1))
  echo "[suite] (${idx}) TOPLEVEL=${toplevel} MODULE=${module} TESTCASE=${testcase} SEED=${seed}"

  make -C "${SCRIPT_DIR}" \
    "${extra_make[@]}" \
    TOPLEVEL="${toplevel}" \
    RTL_FILELISTS="${rtl_filelists}" \
    MODULE="${module}" \
    TESTCASE="${testcase}" \
    SEED="${seed}" \
    SIM_LOG="${OUT_DIR}/sim_${idx}.log" \
    sim
}

# 2 tops x 2 cases x 2 seeds:
# - adder: tb_top + tests.test_adder
# - fifo : tb_fifo + tests.test_fifo

for seed in "${seeds[@]}"; do
  run_one "tb_top"  "${ROOT_DIR}/filelists/rtl.f"  "tests.test_adder" "run_adder_smoke"  "${seed}"
  run_one "tb_top"  "${ROOT_DIR}/filelists/rtl.f"  "tests.test_adder" "run_adder_random" "${seed}"
  run_one "tb_fifo" "${ROOT_DIR}/filelists/fifo.f" "tests.test_fifo"  "run_fifo_smoke"   "${seed}"
  run_one "tb_fifo" "${ROOT_DIR}/filelists/fifo.f" "tests.test_fifo"  "run_fifo_random"  "${seed}"
done

echo "[suite] Done. Logs in ${OUT_DIR}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEST_DIR="${ROOT_DIR}/tests"

# Output directory (default: sim/regression_out)
OUT_DIR="${REGR_OUT:-${SCRIPT_DIR}/regression_out}"
mkdir -p "${OUT_DIR}"

# Modules to run, space-separated import paths.
# Default: just "${MODULE}" (multi-TOP templates should not blindly run all tests under one TOPLEVEL).
if [[ -n "${REGR_MODULES:-}" ]]; then
  read -r -a modules <<< "${REGR_MODULES}"
else
  if [[ -n "${MODULE:-}" ]]; then
    modules=("${MODULE}")
  else
    modules=()
    shopt -s nullglob
    for f in "${TEST_DIR}"/test_*.py; do
      base="$(basename "$f" .py)"
      modules+=("tests.${base}")
    done
    shopt -u nullglob
  fi
fi

filtered_modules=()
for mod in "${modules[@]}"; do
  if [[ -n "${mod}" ]]; then
    filtered_modules+=("${mod}")
  fi
done
modules=("${filtered_modules[@]}")

if [[ "${#modules[@]}" -eq 0 ]]; then
  echo "[regress] No test modules found." >&2
  exit 1
fi

# Seeds to run, space-separated. Default: current SEED or 42.
if [[ -n "${REGR_SEEDS:-}" ]]; then
  read -r -a seeds <<< "${REGR_SEEDS}"
else
  seeds=("${SEED:-42}")
fi

# Optional clean/rebuild before regression.
REGR_REBUILD="${REGR_REBUILD:-0}"

REGR_SAVE_LOGS="${REGR_SAVE_LOGS:-1}"

# Forward common build/sim config into each "make" invocation (so regress respects
# TOPLEVEL/RTL_FILELISTS/WAVES/COV etc when called from Makefile).
base_make=()
for v in PYTHON_BIN TOPLEVEL RTL_FILELISTS TB_SOURCES W TOP_PARAMS WAVES WAVE_SCOPE WAVE_FILE DEBUG COV COV_DAT_FILE OUT_ROOT COCOTB_PLUSARGS PLUSARGS; do
  if [[ -n "${!v-}" ]]; then
    base_make+=("${v}=${!v}")
  fi
done

sanitize_tag() {
  local v="$1"
  v="${v// /_}"
  v="${v//\//_}"
  v="${v//:/_}"
  v="${v//./_}"
  echo "${v}"
}

REGR_DEBUG="${REGR_DEBUG:-0}"
DEBUG_LOG="${OUT_DIR}/regress_debug.log"
if [[ "${REGR_DEBUG}" == "1" ]]; then
  {
    echo "[debug] REGR_MODULES=${REGR_MODULES-<unset>}"
    echo "[debug] REGR_CASE=${REGR_CASE-<unset>}"
    echo "[debug] REGR_COV_DAT_FILE=${REGR_COV_DAT_FILE-<unset>}"
    echo "[debug] CASE=${CASE-<unset>}"
    echo "[debug] MODULE=${MODULE-<unset>}"
    echo "[debug] COCOTB_TEST_MODULES=${COCOTB_TEST_MODULES-<unset>}"
    echo "[debug] OUT_ROOT=${OUT_ROOT-<unset>}"
    echo "[debug] WAVE_SCOPE=${WAVE_SCOPE-<unset>}"
    echo "[debug] WAVE_FILE=${WAVE_FILE-<unset>}"
    echo "[debug] COV_DAT_FILE=${COV_DAT_FILE-<unset>}"
    echo "[debug] MAKEFLAGS=${MAKEFLAGS-<unset>}"
    echo "[debug] modules=(${modules[*]})"
  } >> "${DEBUG_LOG}"
fi

# Save an environment snapshot for offline debugging (bind to first module)
DOCTOR_OUT="${OUT_DIR}/doctor.log" \
PYTHON_BIN="${PYTHON_BIN:-}" \
TOPLEVEL="${TOPLEVEL:-}" \
COCOTB_TEST_MODULES="${modules[0]}" \
"${SCRIPT_DIR}/doctor.sh"

idx=0
for m in "${modules[@]}"; do
  for s in "${seeds[@]}"; do
    idx=$((idx + 1))
    echo "[regress] (${idx}) MODULE=${m} SEED=${s}"

    if [[ "${REGR_REBUILD}" == "1" ]]; then
      make -C "${SCRIPT_DIR}" clean >/dev/null || true
    fi

    extra_make=()
    if [[ "${REGR_SAVE_LOGS}" == "1" ]]; then
      extra_make+=(COMPILE_LOG="${OUT_DIR}/regr_compile.log")
      extra_make+=(SIM_LOG="${OUT_DIR}/regr_sim_${idx}.log")
    fi

    toplevel="${TOPLEVEL:-tb_top}"
    case_override="${REGR_CASE:-}"
    if [[ -z "${case_override}" ]]; then
      module_tag="$(sanitize_tag "${m}")"
      case_override="regr_${toplevel}__${module_tag}"
    fi
    case_make=()
    if [[ -n "${case_override}" ]]; then
      case_make+=(CASE="${case_override}")
    fi
    # Output artifacts to regression_out directory
    out_root="${OUT_DIR}"
    # Ensure OUT_ROOT is passed to make so it knows where to put the case directory
    base_make+=(OUT_ROOT="${out_root}")

    wave_file_override="${out_root}/${case_override}/seed${s}/waves.vcd"
    wave_make=(WAVE_FILE="${wave_file_override}")
    cov_dat_override="${REGR_COV_DAT_FILE:-}"
    if [[ -z "${cov_dat_override}" ]]; then
      cov_dat_override="${out_root}/${case_override}/seed${s}/coverage.dat"
    fi
    cov_make=(COV_DAT_FILE="${cov_dat_override}")
    if [[ "${REGR_DEBUG}" == "1" ]]; then
      echo "[debug] run ${idx}: TOPLEVEL=${toplevel} CASE=${case_override} MODULE=${m} SEED=${s} WAVE_FILE=${wave_file_override} COV_DAT_FILE=${cov_dat_override}" >> "${DEBUG_LOG}"
    fi

    make -C "${SCRIPT_DIR}" "${base_make[@]}" "${case_make[@]}" "${wave_make[@]}" "${cov_make[@]}" \
      COCOTB_TEST_MODULES="${m}" COCOTB_TESTCASE= TESTCASE= MODULE= \
      SEED="${s}" "${extra_make[@]}" \
      COCOTB_RESULTS_FILE="${OUT_DIR}/regr_results_${idx}.xml"
  done
done

echo "[regress] Done. Results in ${OUT_DIR}"

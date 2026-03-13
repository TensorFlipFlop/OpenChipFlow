# Incremental AI DUT Compatibility Constraints

## Goal

This example constrains the incremental workflow to the already-established `ai_dut` asset set.

## Required Compatibility Rules

- Keep the top-level module name compatible with `ai_tb_top`.
- Keep the cocotb module import compatible with `tests.test_ai`.
- Keep the filelist path valid for `sim/Makefile`.
- Keep the existing smoke testcase entrypoint compatible with `run_basic`.

## Patch Boundary

- Only modify files declared by the handoff manifest allowlist.
- Do not rename design files in P0.
- Do not delete design files in P0.
- Do not regenerate the whole design directory when verify-ready artifacts already exist.

## Verification Expectation

- The downstream workflow must treat these files as authoritative inputs.
- Verification should reuse existing scheduling, testcase validation, trace matrix generation, simulation, and regression stages where possible.

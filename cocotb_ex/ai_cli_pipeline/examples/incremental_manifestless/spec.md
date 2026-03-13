# Incremental AI DUT Spec

## Objective

Use the existing `ai_dut` design assets as the baseline and enter the artifact-first incremental flow without regenerating RTL or cocotb infrastructure.

## Scope

- preserve the current `ai_dut` top-level interface
- preserve the current cocotb module layout
- allow downstream verification to reuse the existing smoke and regression tests

## Compatibility

- keep `ai_tb_top` as the simulation top
- keep `tests.test_ai` as the cocotb module
- keep the existing filelist valid for `sim/Makefile`

# Incremental AI DUT Testplan

## Goal

Validate that the existing `ai_dut` cocotb environment remains usable in the artifact-first incremental flow.

## Testcases

- `TC_SMOKE_001` reuse the existing `run_basic` testcase
- `TC_REGRESSION_001` reuse the existing `tests.test_ai` regression module

## Checks

- testcase discovery succeeds
- smoke execution entrypoint remains stable
- regression module naming remains stable

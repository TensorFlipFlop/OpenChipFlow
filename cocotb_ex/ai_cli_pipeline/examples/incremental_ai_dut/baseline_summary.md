# Incremental AI DUT Baseline Summary

## Task Positioning

This example handoff represents an incremental verification-ready delivery for the existing `ai_dut` design assets in the workspace.

The intent is not greenfield generation.

The intent is:

- preserve the existing `ai_dut` RTL / TB / cocotb assets
- treat the current files as the verified handoff baseline
- allow a downstream workflow to enter verification without regenerating design files

## Baseline Assets

The baseline asset set is:

- `rtl/ai_dut.sv`
- `filelists/ai_dut.f`
- `tb/hdl/ai_tb_top.sv`
- `tb/ai_tb.py`
- `tests/test_ai.py`

## Baseline Verification Inputs

The existing verification planning inputs are:

- `ai_cli_pipeline/specs/out/spec.md`
- `ai_cli_pipeline/specs/out/reqs.md`
- `ai_cli_pipeline/specs/out/testplan.md`

## Example Handoff Purpose

This example exists to validate the `artifact-first incremental flow` plumbing.

It demonstrates that a previous AI session can hand off:

- the planning documents
- the design assets
- the allowed patch scope
- the compatibility notes

and that the current pipeline can consume those artifacts directly.

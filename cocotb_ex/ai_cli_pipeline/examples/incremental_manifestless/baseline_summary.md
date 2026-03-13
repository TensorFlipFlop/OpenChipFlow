# Incremental AI DUT Baseline Summary

## Task Positioning

This handoff describes the existing `ai_dut` baseline and is intended for an incremental, verification-ready workflow.

## Baseline Assets

- `rtl/ai_dut.sv`
- `filelists/ai_dut.f`
- `tb/hdl/ai_tb_top.sv`
- `tb/ai_tb.py`
- `tests/test_ai.py`

## Compatibility Notes

- keep the current interface compatible with `ai_tb_top`
- keep the current cocotb module organization
- keep the patch scope localized to the declared assets

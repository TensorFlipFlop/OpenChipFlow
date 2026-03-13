# Simulation Fix Notes

## Failure Classification
- Failure type: assertion failure (`T-010`, `test_output_register_clear`).
- Precondition check: stimulus was valid (`data_out_valid=1` while `clk2_ready=0`, then `clk2_ready` released).
- Root cause: output monitor sampled on `clk2` rising edge after sequential updates, so a valid transfer cleared in the same edge was not recorded in `captured_words`.

## Changes Applied
- Updated `tb/ai_tb.py`:
  - Changed `_monitor_output()` sampling trigger from `RisingEdge(clk2)` to `FallingEdge(clk2)` to observe stable pre-handshake `valid/ready/data` and record the upcoming transfer.
- No functional RTL change in `rtl/ai_dut.sv`.
- No update required in `tb/hdl/ai_tb_top.sv`, `tests/test_ai.py`, or `filelists/ai_dut.f`.

## Validation
- Pass: `make -C sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_output_register_clear RTL_FILELISTS=../filelists/ai_dut.f sim`
- Pass: `make -C sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_fifo_read_ready_calculation RTL_FILELISTS=../filelists/ai_dut.f sim`
- Pass: `make -C sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_sustained_full_rate_transfer RTL_FILELISTS=../filelists/ai_dut.f sim`

## T_001 Module Resolution Fix

### Failure Classification
- Failure type: simulator compile error (`%Error-MODMISSING`), not an assertion failure.
- Precondition analysis: `tb/hdl/ai_tb_top.sv` instantiates `ai_dut`, but `rtl/ai_dut.sv` declared `module cdc_stream_packer`, so elaboration could not resolve `ai_dut`.

### Changes Applied
- Updated `rtl/ai_dut.sv` module declaration from `cdc_stream_packer` to `ai_dut`.
- No behavioral changes were applied to `tb/hdl/ai_tb_top.sv`, `tb/ai_tb.py`, `tests/test_ai.py`, or `filelists/ai_dut.f`.

### Validation
- Pass: `make -C sim out/ai_tb_top__tests_test_ai__test_input_ready_behavior/seed42/results.xml TOPLEVEL=ai_tb_top MODULE=tests.test_ai TESTCASE=test_input_ready_behavior RTL_FILELISTS=../filelists/ai_dut.f SEED=42`

## T_010 Handshake Sampling Fix (2026-03-06)
- Failure type: assertion failure in `tests.test_ai.test_output_register_clear` (`assert await tb.wait_captured(1)`).
- Root cause: output capture monitor sampled only after `clk2` rising-edge state updates; when `data_out_valid` cleared in the same edge as `ready` acceptance, a legal transfer was not recorded.
- Applied change: updated `tb/ai_tb.py::_monitor_output()` to sample `data_out_valid/clk2_ready/data_out` on `FallingEdge(clk2)` and commit capture on the subsequent rising edge.
- RTL and filelist impact: no behavioral RTL change required; no update required in `rtl/ai_dut.sv`, `tb/hdl/ai_tb_top.sv`, `tests/test_ai.py`, or `filelists/ai_dut.f`.
- Validation: `test_output_register_clear`, `test_fifo_read_ready_calculation`, and `test_sustained_full_rate_transfer` pass with `TOPLEVEL=ai_tb_top` and `RTL_FILELISTS=../filelists/ai_dut.f`.

## T_001 ReadOnly Runtime Fix (2026-03-07)
- Failure type: cocotb runtime error (`RuntimeError: Attempted illegal transition: awaiting ReadOnly in ReadOnly phase`) in `tests.test_ai.test_input_ready_behavior`.
- Root cause: `tb/ai_tb.py::_monitor_output()` executed `await ReadOnly()` twice within one scheduler ReadOnly phase path.
- Applied change: rewrote `_monitor_output()` as an edge-to-edge tracker:
  - sample prior-cycle `data_out_valid/data_out/clk2_rst_n` after a `clk2` rising edge,
  - on each next `clk2` rising edge, capture when prior `valid` and current `ready` indicate a completed transfer,
  - refresh prior-cycle sampled state for the next iteration.
- RTL/TB HDL/filelist impact: no updates required in `rtl/ai_dut.sv`, `tb/hdl/ai_tb_top.sv`, `tests/test_ai.py`, or `filelists/ai_dut.f`.
- Validation:
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_input_ready_behavior RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0`
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_output_register_clear RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0`
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_drain_completion RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0`
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0` (17/17 pass)

## T_006 Stimulus Quiesce And Drain Completion Fix (2026-03-08)
- Failure type: assertion failure in `tests.test_ai.test_hold_buffer_retry` (`assert await tb.drain()`).
- Precondition analysis: the directed test released output backpressure after establishing `hold_valid`, but the helper path could leave `data_in_valid=1`; that kept injecting new input during the drain phase and violated the intended "no new data while draining" condition.
- Root cause:
  - `tb/ai_tb.py::fill_until_hold_valid()` did not quiesce the input stream after the hold buffer condition was reached.
  - `tb/ai_tb.py::_monitor_output()` sampled only post-edge output state, which undercounted legal same-edge handshakes and could keep `drain()` from reaching its completion criterion after the DUT had already gone idle.
  - `tests/test_ai.py::test_drain_completion()` could stop after an odd number of accepted beats, leaving a valid partial packet in `have_a` and making a full idle-state drain impossible by construction.
- Applied change:
  - updated `tb/ai_tb.py::fill_until_hold_valid()` to idle the input stream by default once `hold_valid` asserts;
  - updated `tb/ai_tb.py::_monitor_output()` to capture pre-edge `valid/data` against the next `clk2` edge ready state;
  - updated `tests/test_ai.py::test_drain_completion()` to complete an unmatched accepted beat before asserting full drain completion.
- RTL/TB HDL/filelist impact: no updates required in `rtl/ai_dut.sv`, `tb/hdl/ai_tb_top.sv`, or `filelists/ai_dut.f`.
- Validation:
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_hold_buffer_retry RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0`
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai COCOTB_TESTCASE=test_output_register_clear RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0`
  - `make -C sim sim TOPLEVEL=ai_tb_top COCOTB_TEST_MODULES=tests.test_ai RTL_FILELISTS=../filelists/ai_dut.f COV=0 WAVES=0` (`17/17` pass)

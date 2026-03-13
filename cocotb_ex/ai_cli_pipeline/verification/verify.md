# CDC Stream Packer Verification Notes

## Scope

Reviewed sources:

- `ai_cli_pipeline/specs/out/spec.md`
- `ai_cli_pipeline/specs/out/reqs.md`
- `rtl/ai_dut.sv`
- `tb/hdl/ai_tb_top.sv`
- `tb/ai_tb.py`
- `tests/test_ai.py`

The reviewed verification target is `ai_dut`, instantiated through `ai_tb_top` with `tb_async_fifo_model` providing the CDC FIFO abstraction.

## Verification Method

- `tb/ai_tb.py` creates a cocotb harness with `clk1=10 ns` and `clk2=20 ns`, matching the 100 MHz and 50 MHz specification ratio.
- Accepted input beats are recorded only on `data_in_valid && clk1_ready`.
- Output words are captured only on `data_out_valid && clk2_ready`.
- Internal state is observed by backdoor reads of `a_reg`, `have_a`, `hold_word`, `hold_valid`, `out_data_reg`, and `out_valid_reg`.
- Drain completion is determined from `data_out_valid`, `hold_valid`, `have_a`, and `af_rd_valid`.
- `tests/test_ai.py` contains `run_basic` plus 16 directed cocotb tests. No assertion-based, formal, or structural CDC signoff flow is present in the reviewed scope.

## Assumptions

- The executable validation path is `sim/Makefile`, which uses the repository's cocotb simulation flow and defaults to `SIM=verilator` unless externally overridden.
- `tb_async_fifo_model` is treated as the verification FIFO reference. The reviewed scope does not include a production async FIFO macro or a signoff CDC implementation.
- Full `PACK_ORDER` coverage requires separate compile configurations because `test_packing_both_orders` only checks the compiled parameter value seen by the DUT in a given run.
- Default parameter coverage is limited to `IN_W=1`, `OUT_W=2`, and `FIFO_DEPTH=16`. Wider datapaths and alternate FIFO depths are not exercised by the reviewed tests.
- The reset helper in `tb/ai_tb.py` asserts and releases `clk1_rst_n` and `clk2_rst_n` together. Independent reset sequencing is therefore outside direct coverage.
- Coverage reporting in `sim/Makefile` depends on `verilator_coverage` and `genhtml`. The default validation path should therefore keep `COV=0` unless those tools are intentionally enabled.

## Requirement To Test Mapping

| Requirement | Status | Tests | Notes |
| --- | --- | --- | --- |
| REQ-001 | Covered | `run_basic`, `test_input_ready_behavior` | Handshake acceptance and ready behavior are exercised. |
| REQ-002 | Covered with two builds | `test_packing_both_orders` | Requires separate runs for `PACK_ORDER=0` and `PACK_ORDER=1`. |
| REQ-003 | Partially covered | `run_basic`, `test_fifo_read_to_output`, `test_sustained_full_rate_transfer` | CDC transfer is validated only through integration with `tb_async_fifo_model`. |
| REQ-004 | Covered | `run_basic`, `test_fifo_read_to_output`, `test_output_stability_during_backpressure` | Output handshake and hold behavior are checked. |
| REQ-005 | Partially covered | `test_reset_initialization`, `test_reset_during_active_transfer` | Reset functionality is exercised, but only with both resets asserted together. |
| REQ-006 | Covered | `test_reset_initialization`, `test_reset_during_active_transfer` | All documented state registers are checked for reset-to-zero behavior. |
| REQ-007 | Partially covered | `test_reset_during_active_transfer` | Reset during `hold_valid=1` is covered; reset during isolated `have_a=1` or output hold is not explicitly targeted. |
| REQ-008 | Covered | `test_input_ready_behavior` | `clk1_ready=1` with `have_a=0` is checked. |
| REQ-009 | Covered | `test_input_ready_behavior`, `test_overflow_protection` | `clk1_ready=0` with `have_a=1 && hold_valid=1` is checked. |
| REQ-010 | Covered | `test_first_beat_storage` | First-beat capture into `a_reg` and `have_a` is checked. |
| REQ-011 | Covered | `test_packing_both_orders` | Packed word formation is checked for the compiled order. |
| REQ-012 | Covered | `test_fifo_write_when_ready` | Direct FIFO write without hold buffering is exercised. |
| REQ-013 | Covered | `test_hold_buffer_on_fifo_backpressure` | Hold buffer capture on write backpressure is checked. |
| REQ-014 | Covered | `test_hold_buffer_retry` | Buffered write retry and drain completion are checked. |
| REQ-015 | Environment model only | `test_input_ready_behavior`, `test_hold_buffer_on_fifo_backpressure` | `af_wr_ready` comes from `tb_async_fifo_model`; no standalone FIFO verification exists in the reviewed scope. |
| REQ-016 | Covered | `test_fifo_read_to_output` | FIFO read into `out_data_reg` is checked. |
| REQ-017 | Covered | `test_output_stability_during_backpressure` | Output stability is checked for 50 clk2 cycles of backpressure. |
| REQ-018 | Covered | `test_fifo_read_ready_calculation` | `af_rd_ready` behavior is checked for empty and held-output cases. |
| REQ-019 | Covered | `test_output_register_clear` | `out_valid_reg` clear behavior after consumption is checked. |
| REQ-020 | Covered | `test_partial_packet_state_persistence` | `have_a=1` persistence is checked under downstream backpressure conditions. |
| REQ-021 | Partially covered | `test_sustained_full_rate_transfer` | The test proves eventual acceptance of 1000 beats without data loss, but does not assert cycle-accurate full-rate acceptance or no-bubble behavior. |
| REQ-022 | Covered | `test_input_ready_behavior`, `test_overflow_protection` | Overflow prevention through `clk1_ready` deassertion is checked. |
| REQ-023 | Covered | `run_basic`, `test_drain_completion` | Drain completion is checked against the implemented idle criteria. |

## Coverage Gaps

- Independent asynchronous reset behavior is not covered. The reviewed tests do not assert `clk1_rst_n` and `clk2_rst_n` separately or with skewed release timing.
- Partial-packet discard is only partially covered. No explicit test resets the DUT in the `have_a=1 && hold_valid=0` state.
- Output-side reset interruption is not explicitly covered. The reviewed reset test does not place the DUT in `out_valid_reg=1` with active output backpressure before reset assertion.
- Parameter coverage is narrow. No reviewed test exercises `IN_W > 1`, `OUT_W > 2`, or non-default `FIFO_DEPTH`.
- Illegal configuration coverage is absent. No reviewed test addresses unsupported `PACK_ORDER` values or mismatched `OUT_W != 2 * IN_W`.
- Randomized stress recommended by the specification is absent. `clk2_ready` and `data_in_valid` are driven by directed patterns rather than constrained-random toggling.
- CDC verification is limited to the local FIFO model. Pointer synchronization behavior, implementation-specific latency, and signoff CDC requirements remain outside the reviewed scope.
- The 1000-beat throughput scenario checks data integrity but not cycle-by-cycle throughput guarantees.

## Script Coverage Intent

- Run a smoke validation with `TESTCASE=run_basic`.
- Run the full `tests.test_ai` suite with `PACK_ORDER=0`.
- Rebuild and rerun the full `tests.test_ai` suite with `PACK_ORDER=1`.
- Keep coverage generation optional through `COV=1` so that the default path does not depend on optional coverage tools.

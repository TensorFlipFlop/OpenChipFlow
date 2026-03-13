# REQ -> Testcase -> RTL Signal Trace Matrix

## Inputs

- reqs: `ai_cli_pipeline/specs/out/reqs.md`
- testplan: `ai_cli_pipeline/specs/out/testplan.md`
- tests: `tests/test_ai.py`
- rtl: `rtl/ai_dut.sv`

## Summary

- total requirements: 23
- status OK: 23
- NO_TESTPLAN: 0
- MISSING_TEST_IMPL: 0
- NO_SIGNAL_LINK: 0

## Requirement Trace

| REQ | Test IDs | Testcases | RTL Signals | Status |
|---|---|---|---|---|
| REQ-001 | T-001 | test_input_ready_behavior | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) | OK |
| REQ-002 | T-003 | test_packing_both_orders | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+1) | OK |
| REQ-003 | T-012 | test_sustained_full_rate_transfer | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) | OK |
| REQ-004 | T-012 | test_sustained_full_rate_transfer | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) | OK |
| REQ-005 | T-014 | test_reset_initialization | a_reg<br>have_a<br>hold_valid<br>hold_word<br>out_data_reg<br>out_valid_reg | OK |
| REQ-006 | T-014 | test_reset_initialization | a_reg<br>have_a<br>hold_valid<br>hold_word<br>out_data_reg<br>out_valid_reg | OK |
| REQ-007 | T-015 | test_reset_during_active_transfer | a_reg<br>af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>...(+10) | OK |
| REQ-008 | T-001 | test_input_ready_behavior | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) | OK |
| REQ-009 | T-001 | test_input_ready_behavior | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) | OK |
| REQ-010 | T-002 | test_first_beat_storage | a_reg<br>clk1<br>clk1_ready<br>clk1_rst_n<br>data_in<br>data_in_valid<br>...(+1) | OK |
| REQ-011 | T-003 | test_packing_both_orders | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+1) | OK |
| REQ-012 | T-004 | test_fifo_write_when_ready | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+2) | OK |
| REQ-013 | T-005 | test_hold_buffer_on_fifo_backpressure | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) | OK |
| REQ-014 | T-006 | test_hold_buffer_retry | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) | OK |
| REQ-015 | T-004 | test_fifo_write_when_ready | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+2) | OK |
| REQ-016 | T-007 | test_fifo_read_to_output | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+5) | OK |
| REQ-017 | T-008 | test_output_stability_during_backpressure | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+4) | OK |
| REQ-018 | T-009 | test_fifo_read_ready_calculation | af_rd_ready<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+4) | OK |
| REQ-019 | T-010 | test_output_register_clear | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+3) | OK |
| REQ-020 | T-011 | test_partial_packet_state_persistence | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+1) | OK |
| REQ-021 | T-012 | test_sustained_full_rate_transfer | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) | OK |
| REQ-022 | T-013 | test_overflow_protection | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) | OK |
| REQ-023 | T-016 | test_drain_completion | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) | OK |

## Testcase Signal Links

| Test ID | Testcase | REQs | RTL Signals |
|---|---|---|---|
| T-001 | test_input_ready_behavior | REQ-001<br>REQ-008<br>REQ-009 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) |
| T-002 | test_first_beat_storage | REQ-010 | a_reg<br>clk1<br>clk1_ready<br>clk1_rst_n<br>data_in<br>data_in_valid<br>...(+1) |
| T-003 | test_packing_both_orders | REQ-011<br>REQ-002 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+1) |
| T-004 | test_fifo_write_when_ready | REQ-012<br>REQ-015 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+2) |
| T-005 | test_hold_buffer_on_fifo_backpressure | REQ-013 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) |
| T-006 | test_hold_buffer_retry | REQ-014 | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) |
| T-007 | test_fifo_read_to_output | REQ-016 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+5) |
| T-008 | test_output_stability_during_backpressure | REQ-017 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+4) |
| T-009 | test_fifo_read_ready_calculation | REQ-018 | af_rd_ready<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+4) |
| T-010 | test_output_register_clear | REQ-019 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>data_in<br>...(+3) |
| T-011 | test_partial_packet_state_persistence | REQ-020 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+1) |
| T-012 | test_sustained_full_rate_transfer | REQ-003<br>REQ-004<br>REQ-021 | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) |
| T-013 | test_overflow_protection | REQ-022 | clk1<br>clk1_ready<br>clk1_rst_n<br>clk2_ready<br>data_in<br>data_in_valid<br>...(+2) |
| T-014 | test_reset_initialization | REQ-005<br>REQ-006 | a_reg<br>have_a<br>hold_valid<br>hold_word<br>out_data_reg<br>out_valid_reg |
| T-015 | test_reset_during_active_transfer | REQ-007 | a_reg<br>af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>...(+10) |
| T-016 | test_drain_completion | REQ-023 | af_rd_valid<br>clk1<br>clk1_ready<br>clk1_rst_n<br>clk2<br>clk2_ready<br>...(+5) |

## Notes

- Signal links are auto-derived from `dut.<signal>` references in tests and debug mapping in tb wrapper.
- A debug signal such as `debug_have_a` is mapped to DUT internal signal `have_a` via wrapper assignments.
- This matrix is heuristic/static analysis; final truth remains simulation + verification report.


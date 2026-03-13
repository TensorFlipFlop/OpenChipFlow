# CDC Stream Packer Test Plan

| Test ID | Requirement(s) | Testcase | Description |
| --- | --- | --- | --- |
| T-001 | REQ-001, REQ-004 | `test_default_interface_and_params` | 在默认 elaboration 下检查顶层端口名、`data_in`/`data_out` 位宽以及默认参数值 `IN_W = 1`、`OUT_W = 2`、`PACK_ORDER = 0`。 |
| T-002 | REQ-002, REQ-004 | `test_supported_parameterizations` | 对至少一组非默认合法参数组合分别 elaboration，检查 `IN_W >= 1`、`OUT_W = 2 * IN_W`、`PACK_ORDER` 为 `0` 或 `1` 时顶层端口位宽与参数值一致。 |
| T-003 | REQ-003 | `test_invalid_parameter_rejected` | 对 `IN_W < 1`、`OUT_W != 2 * IN_W`、`PACK_ORDER` 不属于 `{0, 1}` 的非法组合分别运行 elaboration 或仿真启动，检查结果为构建拒绝或初始 fatal 配置错误。 |
| T-004 | REQ-005, REQ-007 | `test_named_state_visibility_and_reset_values` | 通过层次路径读取全部强制命名状态与命名信号，并在对应复位断言期间检查 `a_reg`、`have_a`、`hold_word`、`hold_valid`、`out_data_reg`、`out_valid_reg` 的值均为规范规定的全 `0` 或 `0`。 |
| T-005 | REQ-006 | `test_afifo_clock_reset_mapping` | 检查 `af_wrclk`、`af_wr_rst_n`、`af_rd_clk`、`af_rd_rst_n` 与顶层 `clk1`、`clk1_rst_n`、`clk2`、`clk2_rst_n` 的映射关系。 |
| T-006 | REQ-010, REQ-011, REQ-012, REQ-013, REQ-015 | `test_pack_order_zero_acceptance_and_tail` | 在 `PACK_ORDER = 0` 构建下施加含无效拍与奇数尾拍的输入序列，检查仅 `in_fire` 计入序列，第 `1` 个 beat 写入 `a_reg`，第 `2` 个 beat 形成 `{a_reg, b}`，未配对尾拍保持到后续配对或 `clk1` 复位。 |
| T-007 | REQ-010, REQ-011, REQ-012, REQ-014, REQ-015 | `test_pack_order_one_acceptance_and_tail` | 在 `PACK_ORDER = 1` 构建下施加含无效拍与奇数尾拍的输入序列，检查仅 `in_fire` 计入序列，第 `1` 个 beat 写入 `a_reg`，第 `2` 个 beat 形成 `{b, a_reg}`，未配对尾拍保持到后续配对或 `clk1` 复位。 |
| T-008 | REQ-016, REQ-017, REQ-018, REQ-026 | `test_write_side_hold_priority_and_ready_rule` | 利用内部 `hold_*`、`af_wr_*`、`have_a`、`clk1_ready` 信号构造写侧拥塞场景，检查 `af_wr_valid` 与 `af_wr_data` 组合关系、`hold_word` 优先级、未发送新 word 的 `hold_word` 暂存、`clk1_ready` 公式，以及无更早 `hold_word` 时新 word 在第 `2` 个 beat 被接受的同拍对 `afifo` 可见。 |
| T-009 | REQ-019, REQ-024, REQ-025 | `test_random_backpressure_preserves_sequence` | 在满足平均吞吐约束的时钟配置下施加长序列输入与随机 `clk2_ready` 反压，使用记分板检查 `wr_fire` 到输出的顺序保持、无复制、无丢失、无重排，并在 `clk2_ready` 恢复后验证所有已接受完整 word 最终按序排空。 |
| T-010 | REQ-020, REQ-021 | `test_output_mapping_and_af_rd_ready_rule` | 检查 `data_out = out_data_reg`、`data_out_valid = out_valid_reg`，并验证 `af_rd_ready` 在输出为空、当前输出同拍被消费、以及 `data_out_valid = 1 && clk2_ready = 0` 三种条件下分别取 `1`、`1`、`0`。 |
| T-011 | REQ-022, REQ-027 | `test_same_cycle_refill_no_bubble` | 构造当前输出 word 被消费且 `afifo` 同拍提供下一完整 word 的场景，检查 `af_rd_data` 在同拍装载到 `out_data_reg`、`out_valid_reg` 保持为 `1`，且 `data_out_valid` 不出现空泡。 |
| T-012 | REQ-023 | `test_output_stable_while_blocked` | 当 `data_out_valid = 1 && clk2_ready = 0` 时，连续采样 `data_out` 与 `data_out_valid`，检查其在阻塞期间保持稳定，直到发生 `out_fire` 或 `clk2` 域复位。 |
| T-013 | REQ-028 | `test_boundary_rate_sustained_throughput` | 在默认工作点 `clk1 = 100 MHz`、`clk2 = 50 MHz`、`IN_W = 1`、`OUT_W = 2` 且 `clk2_ready = 1` 持续保持的条件下，检查输入端可按 `clk1` 每拍接受 `1` 个 beat，并在首个输出 word 有效后保持 `clk2` 每拍 `1` 个有效输出且无内部空泡、无丢失、无重排。 |
| T-014 | REQ-008 | `test_clk1_async_reset_discards_partial_and_unwritten_data` | 在 `clk1` 有效边沿之间断言 `clk1_rst_n`，检查复位期间不存在 `in_fire` 或 `wr_fire`，未完成半包与尚未写入 `afifo` 的 `hold_word` 被立即清除，且复位前后的 beat 不会跨复位边界组合为同一输出 word。 |
| T-015 | REQ-009 | `test_clk2_async_reset_invalidates_output` | 在 `clk2` 有效边沿之间断言 `clk2_rst_n`，检查复位期间不存在 `rd_fire` 或 `out_fire`，`data_out` 立即回到全 `0`、`data_out_valid` 立即为 `0`，且复位释放后仅在装载新的完整 word 后重新置为有效。 |

## Spec Gaps / Open Questions

- `T-002`, `T-003`: `ASSUME` 回归环境支持对不同参数组合分别 elaboration，并可可靠捕获 elaboration 失败或仿真初始 fatal 退出状态。
- `T-004`, `T-005`, `T-008`, `T-010`, `T-011`: `ASSUME` 仿真环境允许通过层次路径直接访问规范要求保留的内部命名状态与 `af_*` 信号。
- `T-009`, `T-013`: `TBD` 规范未定义 `clk2_ready` 变化传播到 `clk1_ready` 的固定拍数，也未定义首个输出 word 的固定出现周期；相关测试只能检查顺序完整性、最终排空与稳态吞吐，不能检查固定延迟。
- `T-014`, `T-015`: `ASSUME` 仿真时间精度足以在两个有效时钟边沿之间断言与释放异步复位，并区分同一仿真时间步内的 delta-cycle 更新。

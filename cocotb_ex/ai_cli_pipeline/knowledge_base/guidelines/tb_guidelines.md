# Cocotb Testbench Guidelines

1. **Phase Management**:
   - NEVER drive signals immediately after `await ReadOnly()`.
   - ALWAYS use `await Timer(1, "ps")` or `await RisingEdge(clk)` to exit the ReadOnly phase before assigning values to `dut.signal.value`.

2. **Timer Usage**:
   - `Timer(0)` is deprecated/unsafe. Use `Timer(1, "ps")` for delta delays.

3. **Model Synchronization**:
   - In monitor/driver loops, sample Inputs BEFORE the clock edge (using `await ReadOnly()` before `RisingEdge()`).
   - Sample Outputs AFTER the clock edge (using `await ReadOnly()` after `RisingEdge()`).
   - This ensures your model state matches the RTL's registered logic.

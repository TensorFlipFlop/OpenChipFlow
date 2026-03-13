# RTL Design Guidelines

1. **Reset Logic**:
   - Use asynchronous low-active reset (`rst_n`) consistently.
   - Ensure all control registers are reset.

2. **Combinational Loops**:
   - Avoid combinational loops. Ensure `ready` signals depend on registered state (e.g. `!full`), not directly on input `valid` if possible.

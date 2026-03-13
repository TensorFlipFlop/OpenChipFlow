# AI Knowledge Base Index

This Knowledge Base serves as the long-term memory for the verification environment.

## Directory Structure

*   **`guidelines/`**: Static rules and best practices for code generation.
    *   `rtl_guidelines.md`: For Design Agents (SystemVerilog).
    *   `tb_guidelines.md`: For Verification Agents (Python/Cocotb).
*   **`patterns/`**: Dynamic error matching and resolution strategies.
    *   `fix_patterns.json`: Maps error log signatures to specific fix actions.
*   **`archives/`**: Raw data of historical failures for continuous learning.

## Integration

*   **Generators (DE/DV)**: Must read `guidelines/*.md` to produce high-quality initial code.
*   **Fixers**: Must read `patterns/fix_patterns.json` to apply proven fixes quickly.
*   **Pipeline**: Automates the collection of new failures into `archives/`.

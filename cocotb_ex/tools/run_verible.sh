#!/bin/bash
set -e

# Run Verible Lint on all SystemVerilog files in cocotb_ex/rtl and cocotb_ex/tb
# Usage: ./run_verible.sh

echo "Running Verible Lint..."
find cocotb_ex/rtl cocotb_ex/tb -name "*.sv" -print0 | xargs -0 verible-verilog-lint --rules=-no-tabs,-line-length

echo "Verible Lint complete."
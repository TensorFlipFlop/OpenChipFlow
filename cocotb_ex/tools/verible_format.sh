#!/bin/bash
set -e

# Format all SystemVerilog files in cocotb_ex/rtl and cocotb_ex/tb
find cocotb_ex/rtl cocotb_ex/tb -name "*.sv" -print0 | xargs -0 -I {} verible-verilog-format --inplace "{}"

echo "Formatted SystemVerilog files."

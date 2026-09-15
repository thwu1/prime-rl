#!/usr/bin/env bash
#
# Compile and simulate the flow control wrapper design
# Run from /app directory
#

set -euo pipefail
cd /app

iverilog -g2012 \
    rtl/blackbox/pipe_mult.sv \
    rtl/blackbox/pipe_add.sv \
    rtl/blackbox/pipe_isqrt.sv \
    rtl/compute_pipeline.sv \
    rtl/flow_control_wrapper.sv \
    tb/tb_flow_control.sv \
    -o /tmp/sim_out 2>&1

vvp /tmp/sim_out 2>&1 | \
    grep -v 'dumpfile\|VCD info' | \
    grep -E 'PASS|FAIL|Test|Transfer|error|Error|ERROR|timeout' || true

rm -f /tmp/sim_out dump.vcd /app/dump.vcd

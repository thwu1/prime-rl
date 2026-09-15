#!/bin/bash
cd /app
if [ ! -f tb/tb_verify.v ]; then
    echo "ERROR: Testbench not found at /app/tb/tb_verify.v"
    exit 1
fi
echo "=== Compiling with Icarus Verilog ==="
iverilog -o sim_out rtl/timer_apb.v tb/tb_verify.v
if [ $? -ne 0 ]; then
    echo "COMPILATION FAILED"
    exit 1
fi
echo "=== Running simulation ==="
vvp sim_out

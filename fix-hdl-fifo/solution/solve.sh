#!/bin/bash

cd /app
mkdir -p /app/rtl

# Fix FIFO bugs and create the arbiter module
python3 /solution/solve_system.py

# Compile the complete system with Verilator
verilator --binary --timing -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
  rtl/fifo_pkg.sv rtl/fifo_mem.sv rtl/fifo_ctrl.sv rtl/fifo.sv \
  rtl/dual_fifo_arb.sv rtl/arbiter.sv \
  /tests/tb_dual_fifo_arb.sv --top-module tb_dual_fifo_arb --Mdir /tmp/solve_obj_dir

# Run simulation and verify
/tmp/solve_obj_dir/Vtb_dual_fifo_arb

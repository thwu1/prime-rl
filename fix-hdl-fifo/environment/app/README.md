# Dual-Channel FIFO Arbiter System

A dual-channel synchronous FIFO system with round-robin arbitration, implemented in SystemVerilog.

## Structure
- `rtl/fifo_pkg.sv` — Package with parameters and type definitions
- `rtl/fifo_mem.sv` — Dual-port memory array
- `rtl/fifo_ctrl.sv` — Read/write pointer and flag logic
- `rtl/fifo.sv` — Single-channel FIFO integration
- `rtl/dual_fifo_arb.sv` — Top-level: two FIFOs + arbiter
- `rtl/arbiter.sv` — Round-robin arbiter (missing)
- `tb/tb_dual_fifo_arb.sv` — Verification testbench

## Build
Target simulator: Verilator

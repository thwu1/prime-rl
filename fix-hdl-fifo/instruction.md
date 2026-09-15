A multi-file SystemVerilog project at `/app/` implements a dual-channel FIFO arbiter system: two independent write channels feed data through separate synchronous FIFOs, and a round-robin arbiter merges their outputs onto a single valid/ready output port. The project spans these source files:

- `/app/rtl/fifo_pkg.sv` — Package with shared parameters and type definitions (correct)
- `/app/rtl/fifo_mem.sv` — Dual-port memory array for FIFO storage
- `/app/rtl/fifo_ctrl.sv` — Read/write pointer management and status flags
- `/app/rtl/fifo.sv` — Single-channel FIFO integrating memory and control
- `/app/rtl/dual_fifo_arb.sv` — Top-level system integrating two FIFOs and the arbiter (correct)
- `/app/rtl/arbiter.sv` — **Missing**: the round-robin arbiter module does not exist
- `/app/tb/tb_dual_fifo_arb.sv` — Verification testbench (correct)

The FIFO modules (`fifo_mem.sv`, `fifo_ctrl.sv`, `fifo.sv`) contain multiple bugs spanning cross-file dependency issues (missing imports, incorrect port names, wrong parameter references) and hardware design logic errors (pointer arithmetic, status flag generation). The package, top-level integration, and testbench are correct and must not be modified.

The arbiter module referenced by `dual_fifo_arb.sv` has not been implemented. Design and implement `/app/rtl/arbiter.sv` as a round-robin arbiter that uses valid/ready handshaking on both input channels and the output port, alternates priority between channels when both have data (channel A has initial priority after reset), falls through to the available channel when only one has data, and respects output backpressure by not consuming input data when the output is not ready.

Debug and fix all FIFO RTL bugs, then implement the arbiter so that the complete system compiles with Verilator and the simulation reports `PASS: All tests passed`.
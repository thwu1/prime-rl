A Verilator-based SystemVerilog project at `/app/` implements a pipelined FIR filter. Running `make run` should build and simulate the design, producing output files in `/app/` — but the core module `src/fir_engine.sv` contains only port declarations with no internal logic.

These files define the interface contract and must not be modified:
- `src/fir_pkg.sv` — parameter package (data widths, tap count)
- `src/fir_top.sv` — top-level wrapper instantiating `fir_engine`
- `sim/sim_main.cpp` — C++ testbench driving the simulation
- `Makefile` — build rules

An earlier engineer's attempt at a filter implementation exists in `src/fir_core.sv` and `src/coeff_rom.sv`. This approach has fundamental architectural limitations that prevent it from satisfying the testbench's requirements, plus implementation bugs at multiple levels. These files are not compiled by the Makefile — study them to understand what went wrong, but implement your solution in `fir_engine.sv`.

The testbench in `sim/sim_main.cpp` is the definitive behavioral specification. It exercises five scenarios covering coefficient loading protocol, impulse response correctness with both positive and negative coefficients, coefficient management semantics under partial updates, and output pipeline timing. Derive all behavioral requirements — interface protocol, timing constraints, reset behavior, and coefficient lifecycle — from the testbench source code and the module port interface.

All five test scenarios must produce correct output files for the simulation to pass.
Implement a VLIW backend compiler and integrate it with the provided toolchain to produce verified, optimized machine code.

The environment at `/app/` contains:

- `vliw.py` — VLIW processor model with 4 issue slots per cycle (2 ALU, 1 MUL, 1 MEM), latency-aware pipeline stalls, and a cycle-accurate Python simulator. Defines the `Program`, `CompiledProgram`, `PhysInst`, and `VLIWBundle` data structures.
- `programs.py` — Four test programs as SSA-form instruction sequences with virtual registers. Each specifies a register limit (`max_regs`) and cycle-count target.
- `tools/vsim.c` — A cycle-accurate VLIW simulator written in C. Must be compiled with `gcc` to produce a working binary at `/app/tools/vsim`. Reads `.vbin` interchange files and reports cycle counts and memory state. See its header for the `.vbin` format spec.
- `tools/vexport.py` — CLI tool that imports your `backend.py`, compiles each program, and writes `.vbin` interchange files consumable by `vsim`.
- `tools/vdot.py` — CLI tool that reads `.vbin` files and generates Graphviz DOT dependency graphs showing the VLIW schedule structure.

Your `compile(program, max_regs)` function in `/app/backend.py` must transform each program into a `CompiledProgram` of `VLIWBundle` objects that:
- Produces identical memory output (addresses 0 through `data_size - 1`) as `simulate_sequential`
- Uses no more than `max_regs` physical registers (r0 is hardwired to zero)
- Achieves total cycle count at or below each program's target

Two test programs have `max_regs` smaller than peak live register count, requiring spill code via scratch memory (addresses `data_size` through 255).

You must also build the C simulator from `/app/tools/vsim.c`, use it together with `vexport.py` to validate all four compiled programs as `.vbin` files in `/app/output/`, and produce DOT and SVG dependency-graph visualizations in `/app/output/` using `vdot.py` and `graphviz`.
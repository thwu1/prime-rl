A VLIW processor toolchain is provided at `/app/`. The architecture is specified in `/app/machine.spec`: 3 execution slots per cycle (A for ALU, B for ALU+MUL, M for LOAD/STORE), 24 physical registers (r0 hardwired to 0), and variable-latency instructions (ALU=1, MUL=2, LOAD=3 cycles). Reading a register with an unresolved pending write is a RAW hazard error.

Five SSA test programs in `/app/programs.py` use virtual register names and perform integer hashing, polynomial evaluation, tree traversal, and matrix multiplication.

Implement `/app/optimizer.py` providing both:

- **Python API**: `optimize(instructions, num_regs, mem_size)` takes SSA tuples with virtual registers, returns VLIW bundle dicts with physical register indices. The existing stub documents the function signature and bundle format.

- **CLI mode**: `python3 optimizer.py <program_name>` outputs scheduled bundles in `.vliw` text format to stdout, consumable by the toolchain.

The toolchain includes a C-based bundle validator at `/app/bundle_check.c`. Compile it via `make build` in `/app/`. Use `./bundle_check <file.vliw>` to validate slot constraints, register ranges, and WAW conflicts. Use `python3 machine.py simulate <file.vliw> --init <program> [--trace]` for cycle-accurate execution and `python3 machine.py compare <file.vliw> <program>` to verify against reference. Run `make verify-all` for the full pipeline across all programs.

The optimizer must map virtual registers to physical registers, schedule instructions into VLIW bundles respecting data dependencies and latencies, avoid all hazards, produce correct memory state, and meet per-program cycle count targets.
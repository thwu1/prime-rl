Implement a complete register allocator in `/app/allocator.py` that transforms x86-64 programs with virtual variables into programs using only physical registers and stack locations.

The `/app/` directory contains:
- `ir.py` — IR definitions (instruction/operand types, `reads()`/`writes()` helpers, register sets)
- `graph.py` — Undirected/directed adjacency list graph library with `UndirectedAdjList`
- `priority_queue.py` — Max-heap priority queue for DSATUR vertex ordering
- `programs.py` — Six test programs as `X86Program` CFGs (straight-line, diamond, loop, high-pressure, function call, move chain)
- `emulator.py` — x86 emulator that validates execution correctness (clobbers caller-saved registers on `callq`)
- `allocator.py` — Stub with function signatures; implement all seven functions

Implement all functions in `/app/allocator.py`:

- **`uncover_live`**: Backward dataflow liveness analysis across arbitrary CFGs. Must use fixed-point iteration for programs with loops (back-edges). A jump to `conclusion` makes `%rax` live.
- **`build_interference`**: Construct the interference graph. Three rules: general writes-vs-live, call clobbers all caller-saved, move skips source-destination edge.
- **`build_move_graph`**: Record which variable pairs are connected by `movq` instructions.
- **`color_graph`**: DSATUR graph coloring. Pre-color physical registers in `ALLOCATABLE` (color 0 = `rcx`, ..., 11 = `r14`). Break saturation ties by move-related score. Bias color selection toward move-related neighbors' colors. Colors >= 12 are stack spills.
- **`assign_homes`**: Map colors to `Reg`/`Deref('rbp', offset)`. Compute 16-byte-aligned `stack_space`. Track used callee-saved registers.
- **`patch_instructions`**: Remove trivial `movq X, X`. Fix two-memory-operand violations by routing through `%rax`.
- **`allocate_registers`**: Orchestrate the full pipeline.

Conventions: 12 allocatable registers (see `ir.ALLOCATABLE`). `%rax` reserved for return values and as a patching temporary. `%rbp`, `%rsp`, `%r15` reserved. Programs terminate by jumping to `conclusion` with the result in `%rax`.
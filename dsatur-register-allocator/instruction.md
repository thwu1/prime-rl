The pseudo-x86 compiler framework at `/opt/regalloc/` generates programs whose operands include unresolved symbolic variables (`Variable` nodes). These programs cannot execute until every variable is mapped to a physical x86-64 register or stack memory slot without conflicts between simultaneously-live values.

Seven test programs of increasing complexity are in `/opt/regalloc/programs.py`: straight-line arithmetic, branches, loops (including nested), function calls with cross-call variable lifetimes, and a high-pressure case with 13 simultaneously live variables (exceeding the 11 allocatable registers). The framework provides IR data structures (`ir.py`), an undirected graph library (`graph.py`), an x86 emulator (`emulate.py`), and a C runtime with `print_int`/`read_int` implementations (`runtime.c`).

Deliver two modules in `/app/`:

1. **`register_allocator.py`** — implements the function signatures defined in the existing stub. Must produce correct, conflict-free register assignments for all seven test programs. Allocation quality matters: programs whose variable pressure fits within the register file should use no stack spills.

2. **`emit_asm.py`** — implements the interface defined in the existing stub. Must emit valid AT&T-syntax x86-64 assembly for each allocated program, compilable via `gcc` with the provided C runtime, producing output identical to the emulator when executed as a native binary.
Build a compilation backend at `/app/` that transforms pseudo-x86 programs with unlimited named variables into working x86-64 executables.

Input programs in `/app/programs.py` use a tuple-based IR where `("var", "x")` represents a virtual variable, `("reg", "rax")` a physical register, `("deref", "rbp", -8)` a stack memory location, and `("imm", 42)` an immediate value. Programs consist of labeled basic blocks forming a control-flow graph.

Your backend must produce two modules:

**`/app/allocator.py`** — exports `allocate_registers(program) -> program`
Replaces every `("var", ...)` with a physical x86-64 location (`("reg", name)` or `("deref", "rbp", offset)`), satisfying all hardware and ABI constraints.

**`/app/emit.py`** — exports `emit_x86(program) -> str`
Converts an allocated program into AT&T-syntax x86-64 assembly text. The C runtime at `/app/runtime.c` provides `main()` (which calls `program_entry()`) and `print_int()`. Compile with:
```
gcc -no-pie -o binary output.s /app/runtime.c
```

The resulting executables must produce correct results for all 7 test programs, which exercise loops, register pressure exceeding available physical registers, and function calls.

Available at `/app/`: `graph.py`, `priority_queue.py`, `programs.py`, `emulator.py`, `runtime.c`.
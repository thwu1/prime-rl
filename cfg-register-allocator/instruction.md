Implement a register allocation pipeline that compiles x86-64 IR programs containing virtual `Var` operands into working ELF executables.

**`/app/allocator.py`** — Export `allocate_registers(program: X86Program) -> X86Program`. Replace every `Var` with a physical `Reg` or stack-relative `Deref('rbp', offset)`. Set `stack_space` on the returned program (non-negative, 16-byte aligned). Eliminate trivial self-moves. The allocated program must produce identical interpreter results to the original via `/app/interp.py`.

**`/app/emitter.py`** — Export `emit_program(program: X86Program, path: str)`. Write GAS AT&T-syntax x86-64 assembly that compiles with `gcc -o <bin> <file>.s /app/runtime.c -no-pie` into a binary that prints `rax` as a decimal integer with newline, then exits 0. Handle the two-memory-operand restriction.

`/app/` provides: `ir.py` (IR types `Imm`/`Reg`/`Var`/`Deref`/`Instr`/`X86Program`, instruction analysis helpers `reads_of`/`writes_of`/`block_successors`, register set constants), `interp.py` (reference interpreter), `framework.py` (`UndirectedAdjList` graph), `programs.py` (8 test programs with expected outputs), and `runtime.c` (C entry point calling `_program_entry`, plus `read_int` for stdin).

Test programs cover arithmetic, branches, loops, Fibonacci, 15-variable spill forcing, `callq` with caller-saved semantics, nested conditionals, and loop-with-conditional bodies.
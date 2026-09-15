`/app/` contains an incomplete x86-64 compiler backend. Provided files include x86 AST definitions (`x86_ast.py`), an x86-64 emulator (`emulator.py`), ten test programs using virtual registers (`programs.py`), a C runtime (`runtime.c`), a `Makefile`, and a compilation driver (`compile_driver.py`).

Two stubs require implementation:

**`/app/allocator.py`** — `allocate_registers(program: X86Program) -> X86Program`
Input programs use `Variable` pseudo-registers. The output must replace every `Variable` with a physical `Reg` or stack-slot `Deref('rbp', offset)`. Allocatable registers: `rcx rdx rsi rdi r8 r9 r10 rbx r12 r13 r14` (11 total); `rax` and `r11` are scratch. Caller-saved registers (`rax rcx rdx rsi rdi r8 r9 r10 r11`) are trashed on every `callq`. No two-operand instruction may have two `Deref` operands. The output must include a `main` block (function prologue) and `conclusion` block (epilogue) with stack frame setup, callee-saved register preservation, and `retq`.

**`/app/codegen.py`** — `emit_x86(program: X86Program) -> str`
Emit AT&T-syntax x86-64 assembly from the allocated program. The `main` block becomes global symbol `compiler_main`; other labels use `.L` prefix. Output must assemble and link with `/app/runtime.c` via the `Makefile`.

Run `make all` in `/app/` to build all programs as native x86-64 binaries. The test suite validates both emulator and native execution correctness.
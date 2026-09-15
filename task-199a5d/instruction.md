Implement two modules for the three-address code IR defined in `/app/ir.py`:

**Register Allocator** (`/app/regalloc.py`): Implement the `allocate_registers(program: Program) -> Program` function. Given a `Program` using virtual registers (`v0`, `v1`, ...), return a new `Program` that uses only the 6 physical registers (`r0`–`r5`) and stack slots (`s0`, `s1`, ...) when register pressure exceeds capacity. The allocated program must satisfy all of the following:

- No virtual registers remain in the output — every operand must be a physical register (`r0`–`r5`) or a stack slot (`s0`, `s1`, ...).
- Physical register indices must be less than `NUM_PHYS_REGS` (6), i.e., only `r0` through `r5` are valid.
- The emulator output of the allocated program must exactly match the emulator output of the original program.
- No trivial self-moves: `MOV rx rx` instructions (where source and destination are the same register) must not appear in the output.
- Programs whose names start with `spill` (see `/app/test_programs.py`) have more simultaneously live variables than physical registers; these programs must use at least one stack slot (`s0`, `s1`, ...) in the allocated output.

**x86-64 Code Generator** (`/app/codegen.py`): Implement the `generate_x86(program: Program) -> str` function. Given an allocated `Program` (containing only `r0`–`r5` and stack slots), produce AT&T-syntax x86-64 assembly text. The assembly must define a `.globl program_entry` symbol and call `print_int` (provided by `/app/runtime.c`) for `PRINT` instructions. The generated assembly is compiled and linked with:

```
gcc -o <binary> <asm_file> /app/runtime.c -no-pie
```

The resulting native binary must exit with code 0 and produce output identical to the emulator's output for the same program.

The IR supports arithmetic (`ADD`, `SUB`, `MUL`, `MOD`), comparisons (`CMP_LT`, `CMP_EQ`), register copies (`MOV`), output (`PRINT`), and control flow (`BR`, `JMP`, `RET`). Programs are structured as labeled basic blocks. See `/app/ir.py` for the `Instr` and `Program` API, `/app/emulator.py` for reference semantics, and `/app/test_programs.py` for 11 test programs spanning straight-line code, branches, loops, and high-register-pressure scenarios requiring spills.
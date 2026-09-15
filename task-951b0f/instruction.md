The compiler framework at `/app/` represents programs as control-flow graphs of pseudo-x86-64 instructions that use virtual registers (`VReg`). Two backend passes are unfinished:

**`/app/allocator.py`** — Must map every virtual register to a physical machine location, producing a semantically equivalent CFG.

**`/app/emitter.py`** — Must translate an allocated CFG into GNU Assembler (GAS) x86-64 assembly source that compiles and links with `/app/runtime.c` via `gcc` to produce a correct executable.

Study the framework source files in `/app/` to understand the IR, instruction semantics, machine constraints, and test programs.

Verify: `cd /app && python3 -m pytest /tests/test_state.py -v`
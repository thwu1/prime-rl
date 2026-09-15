A SysY language parser is provided at `/app/parser.py`. The SysY language specification is at `/app/spec/sysy_spec.md`, the AST format at `/app/spec/ast_spec.md`, and LLVM IR reference notes at `/app/spec/llvmir_notes.md`.

Test programs are in `/app/programs/` (one `.sy` file per subdirectory). A C implementation of the SysY runtime library is at `/app/lib/sysy_runtime.c`.

Implement `/app/codegen.py` -- a code generator that reads a SysY source file, parses it using the provided parser, and produces LLVM IR text (`.ll`) that can be compiled with `clang` and linked with the provided runtime:

```
python3 /app/codegen.py input.sy -o output.ll
clang output.ll /app/lib/sysy_runtime.c -o prog
./prog
```

The compiled programs must produce identical stdout and exit codes to reference C compilation (`gcc /app/lib/sysy_runtime.c program.sy -o prog && ./prog`; SysY is a syntactic C subset). LLVM tools such as `llvm-as` (to validate IR syntax), `opt` (to verify and optimize IR), and `lli` (to interpret IR) are installed and available for development and debugging.

The code generator must produce well-formed LLVM IR that correctly handles all SysY language features including: basic block structure with proper terminators, the alloca/load/store memory model (or SSA with phi nodes), `getelementptr` for array element addressing including multi-dimensional arrays, opaque pointer types (`ptr`), `sdiv`/`srem` for C-style truncating integer division and modulo, short-circuit evaluation of `&&` and `||` using conditional branches with correct side-effect suppression, nested block scoping with variable shadowing, array parameters passed as opaque pointers (including sub-array slicing via GEP), `break`/`continue` via branch instructions to loop headers/exits, `const` declarations with compile-time evaluation, global variables with static LLVM IR initializers (`zeroinitializer` and constant aggregate syntax), and `declare` directives for the SysY runtime library's external functions.
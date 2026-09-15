Build a complete compilation pipeline that translates SysY programs (a C subset used in Chinese national compiler design competitions) into LLVM IR, links them with a precompiled runtime library, and executes them using the LLVM interpreter.

## Deliverables

1. **Compiler** — a program (any language) invoked as `/app/sysy_compiler <file.sy>` that reads a SysY source file and writes LLVM IR (textual `.ll` format) to stdout.

2. **Makefile** at `/app/Makefile` that, when `make` is run, compiles `/app/runtime/sylib.c` to LLVM bitcode at `/app/runtime/sylib.bc` using `clang -emit-llvm`.

3. **Pipeline script** at `/app/sysy_run` that, given a `.sy` file path as its sole argument:
   - Invokes the compiler to produce LLVM IR in a temp file.
   - Uses `llvm-link` to merge the program IR with `/app/runtime/sylib.bc`.
   - Uses `lli` to execute the linked bitcode.
   - Passes stdin through to `lli` and forwards `lli`'s stdout.
   - Exits with `lli`'s exit code.

## SysY Language

The full grammar and semantics are at `/app/spec/sysy_spec.md`. Key features the compiler must handle:

- `int` scalars and multi-dimensional arrays with brace-matched initialization (mixed braced/unbraced values, implicit zero-fill)
- `const` declarations with compile-time evaluation
- Functions with `int` and array parameters (arrays passed by reference, first dimension unsized)
- `if`/`else`, `while`/`break`/`continue`, `return`
- Short-circuit `&&`/`||`
- Unary `+`/`-`/`!`, arithmetic `+`/`-`/`*`/`/`/`%`, comparisons `<`/`>`/`<=`/`>=`/`==`/`!=`
- Integer division truncates toward zero
- Block-level scoping with shadowing
- Decimal, octal (`077`), and hexadecimal (`0xFF`) integer literals
- Single-line (`//`) and multi-line (`/* */`) comments

## Runtime Library

These functions must be declared in the generated IR (matching the signatures in `/app/runtime/sylib.h`) but not defined — they are provided by the linked runtime bitcode:

- `int getint()` — read one integer from stdin
- `void putint(int)` — print integer (no newline)
- `void putch(int)` — print character

## LLVM IR Requirements

The generated IR must be valid LLVM IR that `llvm-as` accepts. It must use `i32` for int values and appropriate pointer/array types. Runtime functions must be declared with `declare` (not defined).

## Reference Materials

- Language specification: `/app/spec/sysy_spec.md`
- Runtime library: `/app/runtime/sylib.h`, `/app/runtime/sylib.c`
- Test programs: `/app/test_programs/`
- Test inputs: `/app/test_inputs/`
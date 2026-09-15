Build a compiler pipeline that translates SysY programs into LLVM IR and executes them via the LLVM toolchain.

Your deliverable is an executable at `/app/sysy_run` that accepts a SysY source file as its sole argument, reads stdin if the program uses input functions, writes program output to stdout, and exits with `main()`'s return value (modulo 256).

The pipeline must:
- Compile SysY source to valid LLVM IR (`.ll` textual format)
- Compile the SysY runtime library at `/app/runtime/sylib.c` to LLVM bitcode using `clang -c -emit-llvm`
- Link the generated IR with the runtime bitcode using `llvm-link`
- Execute the linked result with `lli`

The environment provides LLVM 18 tools (`clang`, `lli`, `llvm-link`, `llvm-as`, `opt`). LLVM 18 uses opaque pointer syntax exclusively (`ptr` instead of typed pointers like `i32*`).

The full SysY language specification is at `/app/spec/sysy_spec.md`. The runtime library implements `getint()`, `getch()`, `getarray()`, `putint()`, `putch()`, `putarray()` — source at `/app/runtime/sylib.c` with header `/app/runtime/sylib.h`. Test programs are in `/app/tests/` (each `test_XX.sy` with optional `test_XX.in` for stdin).

Your compiler must correctly handle all SysY features:
- Integer literals (decimal, hexadecimal `0x1A`, octal `077`)
- Global and local variable declarations with optional initializers
- Multi-dimensional arrays with nested initializer lists and partial initialization
- `const` declarations with compile-time constant expression evaluation for array dimensions
- Functions with `int`/`void` return types, recursion, and early `return` from void functions
- Array parameters passed by reference (`int a[]`, `int a[][3]`), including 2D arrays
- Block scoping with variable shadowing; global variables zero-initialized
- All arithmetic (`+`,`-`,`*`,`/`,`%`), relational (`<`,`>`,`<=`,`>=`,`==`,`!=`), and logical (`&&`,`||`,`!`) operators with correct C-style precedence
- Integer division/modulo truncated toward zero (C99 semantics for negative operands)
- Short-circuit evaluation for `&&` and `||`
- Control flow: `if`/`else` (with correct dangling-else binding), `while` with `break`/`continue`
- Runtime library: `getint()`, `getch()`, `getarray(int[])`, `putint(int)`, `putch(int)`, `putarray(int, int[])`

```
```
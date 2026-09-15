Build a compiler that translates SysY programs into valid LLVM IR. SysY is a statically-typed, integer-only subset of C used in the Chinese national compiler design competition (Huawei BiSheng Cup).

The SysY language specification is at `/app/spec/`. The SysY runtime library C source is at `/app/runtime/sylib.c`, with a pre-built shared library at `/app/runtime/sylib.so` and LLVM bitcode at `/app/runtime/sylib.bc`.

Your compiler must be an executable at `/app/sysy_compiler` that takes a `.sy` file path as its sole argument and writes valid LLVM IR (textual `.ll` format) to stdout.

The compiler must correctly handle all SysY language features: global and local variable declarations (including `const`), multi-dimensional arrays with C-style brace-elision initialization, short-circuit evaluation of `&&` and `||`, lexical scoping with variable shadowing, `while` loops with `break`/`continue`, user-defined functions (both `int` and `void` return types, with early `return`), array parameters (including passing sub-arrays such as `mat[i]` to a function expecting `int arr[]`), integer literals in decimal, octal, and hexadecimal, and unary operators (`-`, `+`, `!`). The runtime library functions (`getint`, `getch`, `getarray`, `putint`, `putch`, `putarray`) must be callable from SysY programs.

The generated IR must satisfy all of the following:

- Parseable by `llvm-as` (syntactically valid)
- Passes `opt -S -passes=verify -o /dev/null` (semantically valid)
- Linkable via `clang -o exe output.ll /app/runtime/sylib.c -Wno-override-module`
- Executable via `lli --load=/app/runtime/sylib.so output.ll`
- Produces correct output and exit codes matching SysY program semantics

Sample programs are in `/app/samples/`. LLVM 18 tools (`clang`, `lli`, `opt`, `llvm-as`, `llvm-link`, `llvm-dis`) are pre-installed.
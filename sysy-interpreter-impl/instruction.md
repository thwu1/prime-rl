Create a compiler at `/app/sysyc` that translates SysY programs into LLVM IR. SysY is a C subset used in Chinese national compiler design competitions (Huawei BiSheng Cup).

The SysY language specification is at `/app/spec/sysy_spec.md`. Sample programs are at `/app/tests/*.sy`. The SysY runtime library (providing `getint`, `putint`, `getch`, `putch`, `getarray`, `putarray`) is pre-compiled as LLVM bitcode at `/app/runtime/sylib.bc`; its C source is at `/app/runtime/sylib.c`.

The compiler must accept a `.sy` file path as its sole command-line argument and output valid LLVM IR to stdout. The generated IR will be verified through this LLVM toolchain pipeline:

```
/app/sysyc test.sy > out.ll && llvm-as out.ll -o out.bc && llvm-link out.bc /app/runtime/sylib.bc -o linked.bc && lli linked.bc
```

The compiled program's stdout and exit code (`main()`'s return value modulo 256) must match the SysY specification. The compiler must correctly handle all SysY features including: multi-dimensional array initializers with brace-elision and partial initialization rules, short-circuit evaluation of `&&` and `||` with observable side effects, lexical scoping with variable shadowing across nested blocks, arrays passed by reference to functions (including 2D array parameters like `int m[][N]`), `break`/`continue` semantics in loops, octal and hexadecimal integer literals, C-style integer division truncating toward zero, constant expressions used as array dimensions, and both comment styles.

Available LLVM tools: `clang`, `llvm-as`, `lli`, `llvm-link`, `llvm-dis`, `opt`. Use `clang -S -emit-llvm` on simple C programs to study LLVM IR examples.
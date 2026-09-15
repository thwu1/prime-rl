Implement a compiler that translates LLVMlite IR (a subset of LLVM IR) to x86-64 assembly. Create an executable script at `/app/compile.py` that accepts an input `.ll` file path and an output `.s` file path:

```
/app/compile.py input.ll output.s
```

Nine LLVMlite IR programs are provided in `/app/programs/`. A C runtime is at `/app/runtime.c`. The generated `.s` assembly must link with the runtime via `gcc -o output output.s /app/runtime.c -no-pie` and the resulting executables must produce correct output.

The LLVMlite IR subset your compiler must handle:

- **Types**: `i64`, `i1`, pointer types (`i64*`, `i8*`, `i8**`), `void`
- **Arithmetic**: `add`, `sub`, `mul` on `i64`
- **Comparison**: `icmp` with conditions `eq`, `ne`, `slt`, `sle`, `sgt`, `sge`
- **Memory**: `alloca`, `load`, `store`, `getelementptr` (single index on typed pointers)
- **Control flow**: `br` (conditional and unconditional), `ret` (typed and void)
- **SSA**: `phi` nodes with labeled incoming edges
- **Calls**: `call` to defined and declared functions, with up to 6 arguments
- **Conversions**: `zext i1 to i64`
- **Globals**: `@name = global i64 <init>` definitions, external `declare` statements

The runtime provides `_print_int(i64)`, `_print_string(i8*)`, and `_alloc_array(i64) -> i64*`. The runtime's `main()` calls your `_program` function and prints its return value. Generated assembly must use AT&T syntax and follow the System V AMD64 ABI calling convention.
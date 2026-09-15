Implement a compiler that translates LLVMlite intermediate representation to x86-64 assembly for Linux. The full language specification is at `/app/spec.md`. A C runtime for linking is at `/app/runtime.c`. Test programs are in `/app/tests/`.

Your compiler must be invocable as:

```
python3 /app/compiler.py <input.ll> -o <output.s>
```

The generated `.s` file must be linkable with the C runtime to produce a working executable:

```
gcc -o prog output.s /app/runtime.c -no-pie
```

LLVMlite is a subset of LLVM IR supporting: i1/i64 integer types, arithmetic and bitwise operations, integer comparisons (`icmp`), stack allocation (`alloca`), memory access (`load`/`store`), pointer arithmetic (`getelementptr`), type conversions (`zext`/`trunc`), conditional and unconditional branches, function definitions and calls (including functions with more than 6 arguments requiring stack passing per the System V AMD64 ABI), global variables, and external function calls to the provided runtime.

All test programs define a `@program` entry point. The runtime calls `program()` and uses its return value as the process exit code.
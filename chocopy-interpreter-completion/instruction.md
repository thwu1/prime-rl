Write a source-to-source compiler at `/app/transpile.py` that translates [ChocoPy](https://chocopy.org/) programs into C code. When the generated C is compiled with `gcc` against the provided runtime library and executed, it must produce output identical to a correct ChocoPy implementation.

A C runtime library is provided at `/app/runtime/runtime.h` and `/app/runtime/runtime.c`. It implements tagged-union value representation (`ChpyVal`), arithmetic and comparison operations, object construction with vtable pointers, attribute and subscript access, vtable-based method dispatch (`chpy_call_method`), list operations, iteration helpers, and runtime error handling. Study the runtime API thoroughly — your transpiler must generate C code that uses this API correctly.

A partial interpreter at `/app/chocopy_partial.py` handles basic features (integers, booleans, strings, arithmetic, comparisons, if/while, functions, print/len). You may use it as a reference for ChocoPy semantics, but your transpiler must support the full feature set listed below by generating C against the runtime API.

A `Makefile` at `/app/Makefile` provides:
- `make compile PROG=programs/foo.py` — transpile + compile
- `make run PROG=programs/foo.py` — transpile, compile, execute

Your transpiler is invoked as:

```
python3 /app/transpile.py <input.py> <output.c>
```

It must read a ChocoPy source file, generate a self-contained `.c` file (including `#include "runtime.h"`), and support:

- Integer, boolean, and string literals and operations
- Typed variable declarations (`x: int = 0`)
- Arithmetic (`+`, `-`, `*`, `//`, `%`), comparisons, boolean operators (`and`, `or`, `not`) with short-circuit semantics
- `if`/`elif`/`else`, `while`, `for` loops (over lists and strings)
- Functions with recursion and mutual recursion
- `return` statements, conditional expressions (`x if cond else y`)
- **Classes with single inheritance and vtable-based dynamic dispatch**: class definitions, attribute initialization from declarations, object construction with `__init__`, attribute read/write (`obj.attr`), method calls that dispatch through the runtime vtable on the receiver's dynamic type
- **Lists**: display (`[1,2,3]`), index read/write, concatenation (`+`), `len()`
- **String indexing**: `s[i]`
- The **`is`** operator (reference identity)
- Runtime errors: "Division by zero" (exit 2), "Index out of bounds" (exit 3), "Operation on None" (exit 4)
- Built-ins: `print`, `len`

Test programs are in `/app/programs/`. Refer to the ChocoPy Language Reference at https://chocopy.org/chocopy_language_reference.pdf for the formal specification of type conformance, operational semantics, and scoping rules.
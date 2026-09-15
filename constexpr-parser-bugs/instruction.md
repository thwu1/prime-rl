A C++20 project at `/app/` provides a constexpr stack-based bytecode VM (`/app/include/vm.hpp`) and instruction set (`/app/include/bytecode.hpp`). The VM supports arithmetic, comparisons, conditional jumps, local variable storage, power/modulo operations, and built-in functions.

Implement the compiler in `/app/include/compiler.hpp`. The `cxvm::compile()` function must translate expression strings into executable `Program` objects entirely at compile time (`constexpr`).

The expression language supports:

- Integer and floating-point literals
- Binary operators `+`, `-`, `*`, `/`, `%` (modulo) with standard precedence and left-to-right associativity
- Power operator `^` with **right-to-left** associativity (higher precedence than `*`/`/`/`%`)
- Unary minus (including on parenthesized sub-expressions and chained `--x`)
- Parenthesized grouping
- Single-letter variables `a`-`z` mapped to environment indices 0-25
- Built-in functions `abs(expr)`, `min(expr,expr)`, `max(expr,expr)`, `sqrt(expr)`
- Comparison operators `<`, `>`, `<=`, `>=`, `==`, `!=` (lower precedence than arithmetic, produce 1.0 or 0.0)
- Ternary conditional `cond ? then_expr : else_expr` using JZ/JMP bytecodes
- Let-bindings `let <var> = <expr> in <body>` using STORE_LOCAL/LOAD_LOCAL, with proper scoping (locals shadow globals, nested lets shadow outer bindings)

The compiler must perform multi-pass optimization:

- Constant folding: any sub-expression free of variables must be reduced to a single PUSH_CONST
- Constant comparison folding: e.g., `3 < 5` folds to PUSH_CONST 1.0
- Dead branch elimination: ternary with constant condition must emit only the live branch (no JZ/JMP)
- Constant propagation through let-bindings: `let x = 5 in x + 1` must fold to PUSH_CONST 6.0
- Cascading optimization: `let x = 5 in let y = x + 1 in y * 2` must fold entirely to PUSH_CONST 12.0

Test programs in `/app/tests/` use `static_assert` to verify both computed results and bytecode structure (instruction counts, opcodes). Run `make test` in `/app/` to validate.
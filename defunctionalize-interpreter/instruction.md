`/app/lang.py` defines a mini functional language (integers, booleans, lambdas, application, let-bindings, recursive functions) and a direct recursive interpreter `eval_direct`. This interpreter relies on Python's call stack and crashes with `RecursionError` on deeply recursive programs.

`/app/ops.c` provides a native C implementation of the language's binary operator evaluation. It supports all standard operators (`+`, `-`, `*`, `//`, `%`, `==`, `!=`, `<`, `>`, `<=`, `>=`) plus a modular exponentiation operator (`^^`) that is not available in the Python reference interpreter.

Create `/app/pipeline.py` that exports a function `run(expr: Expr) -> value` which:

- Produces identical results to `eval_direct` for all programs using standard operators
- Evaluates programs with arbitrary recursion depth (tens of thousands of levels) without stack overflow, even when `sys.setrecursionlimit` is set to 500
- Compiles `/app/ops.c` into a shared library at `/app/libops.so` and uses its `eval_binop` and `op_from_string` functions for all binary operator evaluation, including the `^^` operator

The language's AST types (`Var`, `IntLit`, `BoolLit`, `BinOp`, `If`, `Lam`, `App`, `Let`, `LetRec`), value types (`VClosure`, `VRecClosure`), and a suite of test programs `PROGRAMS` are all importable from `/app/lang.py`.
`/app/benchmarks.fpcore` contains 6 floating-point expressions in [FPCore](https://fpbench.org/spec/fpcore-2.0.html) S-expression format. Each suffers from catastrophic cancellation in specific input regions. Build `/app/fp_improver.py` that parses these expressions, evaluates them in float64 and arbitrary precision, and provides algebraically rewritten versions that restore accuracy.

## Required API in `/app/fp_improver.py`

- `parse_fpcore(text) -> list` — Parse FPCore text. Each element must have attributes: `.name` (str), `.params` (list of str), `.body` (expression AST).
- `eval_float64(expr, bindings: dict) -> float` — Evaluate a parsed expression in IEEE 754 float64. `bindings` maps parameter names to float values.
- `eval_exact(expr, bindings: dict, prec=200)` — Evaluate a parsed expression using `mpmath` at the given precision bits. Returns an mpmath value.
- `get_improved(name: str) -> callable` — Given an expression's `:name` string, return a Python function that computes the same mathematical function with improved float64 accuracy. The function takes positional arguments in the same order as the expression's parameter list.

## Accuracy requirement

Each improved function must achieve at least 40 bits of accuracy (out of 53 possible for float64) at inputs where the original expression suffers catastrophic cancellation. Improvements must use algebraic rewrites or compensated library functions — not arbitrary-precision arithmetic at runtime.
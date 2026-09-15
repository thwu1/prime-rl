`/app/` contains a register-based IR framework: a parser (`ir_parser.py`), emitter (`ir_emitter.py`), interpreter (`interpreter.py`), type definitions (`ir_types.py`), and a language spec (`ir_spec.md`). Five IR programs of varying complexity reside in `/app/programs/`. A skeleton optimizer is at `/app/optimize.py` and a skeleton build pipeline at `/app/Makefile`.

## Optimizer

Implement the `optimize()` function in `/app/optimize.py` to transform IR programs, reducing instruction count while preserving semantics. The optimized IR must produce byte-identical printed output when executed by `python3 /app/interpreter.py`.

Required transformations (these interact and must iterate to a fixed point):

- Expressions whose operands are all compile-time constants must be evaluated statically. Conditional branches with statically resolved conditions must become unconditional.
- Blocks not reachable from the function's entry block must be eliminated.
- When identical operations on identical operands appear more than once and no intervening redefinition invalidates the earlier result, the redundant computation must be replaced with a reference to the original.
- Instructions whose destination registers are never consumed — directly or transitively — by any side-effecting instruction (`print`, `ret`, `cbr`, `call`) must be removed.

Invocation: `python3 /app/optimize.py <input.ir> <output.ir>`

Minimum instruction-count reductions: prog1 >= 25%, prog2 >= 20%, prog3 >= 25%, prog4 >= 25%, prog5 >= 15%.

## Build Pipeline

Complete `/app/Makefile` with the following targets:

- `optimize-all` -- runs the optimizer on each of the five programs, writing optimized output to `/app/programs/<name>.opt.ir`
- `verify` -- for each program, runs the interpreter on both original and optimized IR, compares their stdout using `diff`, exits non-zero on any mismatch
- `report` -- generates `/app/optimization_report.json`: a JSON object keyed by program name (`prog1` through `prog5`), each value containing integer fields `original_count` and `optimized_count` and a numeric field `reduction_pct` (percentage, 0-100). The JSON must be assembled using `jq`. Counts must reflect actual instruction totals from the IR files, not hardcoded values.
- `all` (default) -- runs `optimize-all`, `verify`, `report` in sequence
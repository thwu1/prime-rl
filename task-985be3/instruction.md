Region decomposition partitions a function's input space into exhaustive, disjoint regions. Each region pairs a conjunction of boolean constraints on the inputs with a symbolic invariant expression that equals the function's output whenever those constraints hold.

For example, `f(x) = if x > 99 then 100 elif x > 20 then x + 9 elif x > -2 then 103 else 99` decomposes into four regions:

| Constraints | Invariant |
|---|---|
| x > 99 | 100 |
| x <= 99, x > 20 | x + 9 |
| x <= 99, x <= 20, x > -2 | 103 |
| x <= 99, x <= 20, x <= -2 | 99 |

The file `/app/lang.py` defines AST types for a simple functional language (`Const`, `Var`, `BinOp`, `IfExpr`, `Call` for expressions; `Compare`, `And`, `Or`, `Not`, `BoolConst` for boolean expressions; `FuncDef` and `Region`). It also provides concrete evaluators `eval_expr` and `eval_bool`. Example function definitions are in `/app/examples.py`.

Implement `/app/decompose.py` exporting:

```python
def decompose(func: FuncDef, funcs: dict = None, unroll_depth: int = 3) -> list[Region]
```

The returned list of `Region` objects must satisfy all of the following properties:

1. **Coverage** — every possible integer input combination matches at least one region's constraints.
2. **Correctness** — each region's `invariant` evaluates to the same value as calling the function directly, for all inputs satisfying that region's constraints.
3. **Feasibility** — no returned region has unsatisfiable constraints (e.g., a region requiring `x > 10` and `x < 5` simultaneously must not appear).
4. **Disjointness** — each input matches at most one region.
5. **Completeness** — every returned region's `invariant` is a pure `Expr` free of `IfExpr` and `Call` nodes.

The engine must handle:
- Functions with a single parameter and functions with multiple parameters.
- Arbitrarily nested conditional expressions, including conditionals inside arithmetic sub-expressions.
- Recursive functions (those with `is_recursive=True`), where `funcs` maps function names to their `FuncDef` and `unroll_depth` bounds how deeply recursive calls are expanded. Only fully resolved regions (no remaining `Call` nodes) should be returned.
A Sea-of-Nodes IR framework at `/app/ir.py` models integer computations as dataflow graphs. Nodes represent operations (arithmetic, bitwise, comparisons, casts, select) over typed integers (i1/i8/i16/i32/i64). A code generator at `/app/codegen.py` translates IR graphs into C, compiles them with `gcc`, and runs the binaries.

Create `/app/optimizer.py` exporting a single function:

```python
def optimize(graph: Graph) -> None
```

This function must transform IR graphs **in-place** to produce semantically equivalent but simplified programs. It must implement:

- **Constant folding**: evaluate operations on constant inputs with correct 2's-complement overflow semantics across all integer widths (including signed division/modulo with C-style truncation-toward-zero).
- **Algebraic simplification**: identity rules (e.g. `x + 0 → x`, `x * 1 → x`), annihilator rules (e.g. `x * 0 → 0`, `x & 0 → 0`), self-operand rules (e.g. `x - x → 0`, `x & x → x`), and double-inverse elimination for `neg`/`not`.
- **Strength reduction**: replace multiply/divide/modulo by powers of two with shifts and masks.
- **Comparison simplification**: reflexive comparisons (`cmp(x, x)` resolves to known constants based on the comparison type).
- **Select simplification**: constant conditions and identical arms.
- **Cast chain elimination**: redundant trunc/ext roundtrips (e.g. `trunc(zext(x))` back to original width returns `x`).
- **Global Value Numbering (GVN)**: structural hashing with commutative-op canonicalization to deduplicate equivalent subexpressions.
- **Dead code elimination** via `Graph.remove_dead()`.
- **Iterative convergence**: repeat passes until no further simplifications are found (e.g. GVN deduplication can enable `x - x → 0` which enables further folding).

The `Graph` class provides `replace_node(old, new)` for redirecting all uses and `remove_dead()` for eliminating unreachable nodes.

Correctness is verified both through the Python evaluator (`Graph.evaluate()`) and by compiling optimized graphs to C and executing natively via `gcc`. Optimization quality is verified by asserting specific reductions (constants folded, identities eliminated, strength reductions applied, node counts reduced).
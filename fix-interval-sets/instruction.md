`/app/intervals.py` implements set operations over sorted lists of disjoint, non-adjacent, half-open integer intervals `[(lo, hi), ...]` representing sets of integers `{lo, lo+1, ..., hi-1}`. The library enforces strict invariants: intervals are non-empty (`lo < hi`), sorted by `lo`, and strictly separated (`prev_hi < next_lo`). The `validate()` function checks these invariants.

Several operations contain subtle correctness bugs that violate these invariants or produce semantically wrong results. Three additional operations (`complement`, `symmetric_difference`, `normalize`) are unimplemented stubs. `/app/laws.json` lists twelve algebraic laws that should hold for correct interval set implementations.

Find and fix all bugs in `/app/intervals.py`, implement all missing operations, and create a formal verification framework at `/app/verifier.py` that proves the algebraic laws hold.

`/app/verifier.py` must:
- Import and use the `z3` Python package
- Provide `check_law(law_name, bound)` returning `{"verified": bool, "bound": int}`
- Provide `check_operation(op_func, ref_func, num_sets, bound)` returning `(is_correct, counterexample_or_none)` — it must be capable of detecting incorrect operation implementations

Write results to `/app/verification_report.json`: a JSON object mapping each law name from `laws.json` to `{"verified": true, "bound": N}` with `N >= 8`.

All interval set operations must produce outputs that pass `validate()` and are semantically correct against standard set-theoretic definitions.
Build a region decomposition engine that analyzes pure Python functions and decomposes their input space into exhaustive, disjoint behavioral regions.

A **region decomposition** of a function `f` is a collection of regions `{(C_1, I_1), ..., (C_n, I_n)}` where each `C_i` is a conjunction of constraints on the inputs and `I_i` is an invariant expression, satisfying:

- **Correctness**: For all inputs where `C_i` holds, `f(inputs) = I_i(inputs)`.
- **Coverage**: Every possible input satisfies exactly one region's constraints.
- **Minimality**: Every region is feasible (its constraints are satisfiable). Paths with logically contradictory constraints must be excluded.

`/app/functions.py` contains six pure Python functions using integer arithmetic, comparisons, boolean operators, if/else control flow, and local variable assignments (let-bindings). Some functions contain execution paths whose accumulated branch conditions are mutually contradictory and therefore represent infeasible regions that must be detected and excluded.

Create `/app/region_checker.py` that exposes the following interface:

```python
def num_regions(func_name: str) -> int:
    """Return the number of feasible regions for the named function."""

def check_region(func_name: str, region_idx: int, **inputs) -> bool:
    """Return True iff the given inputs satisfy region region_idx's constraints."""

def evaluate_region(func_name: str, region_idx: int, **inputs) -> int:
    """Return the invariant value of region region_idx for the given inputs."""
```

All six functions in `/app/functions.py` must be decomposed. For every input to a function, exactly one region must match, and its invariant must equal the function's actual return value.
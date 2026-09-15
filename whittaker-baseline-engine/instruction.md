Create `/app/baseline_engine.py` — a standalone implementation of penalized least-squares baseline correction that is numerically compatible with the `pybaselines` library's Whittaker module. Only `numpy` and `scipy` may be imported by the delivered module. The `pybaselines` package is available at test time as a reference oracle but must not appear in any import statement in your code.

## Required public interface

**Utility function:**
- `diff_penalty_diags(n, diff_order=2, lower_only=True)` — must produce identical output to `pybaselines._banded_utils.diff_penalty_diagonals` for all valid inputs, sizes, and difference orders.

**Baseline algorithms** (each must match the corresponding function in `pybaselines.whittaker` — same name, same parameter defaults, same return semantics):
- `asls(y, lam=1e6, p=0.01, diff_order=2, max_iter=50, tol=1e-3)`
- `arpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)`
- `iarpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3)`
- `drpls(y, lam=1e5, eta=0.5, diff_order=2, max_iter=50, tol=1e-3)`
- `aspls(y, lam=1e5, diff_order=2, max_iter=100, tol=1e-3, asymmetric_coef=0.5)`

Return value structure, dictionary keys, iteration logic, weighting functions, convergence criteria, parameter validation, and edge-case handling must all match pybaselines exactly. Study the library's source to determine these.

**Meta-selector:**
- `auto_baseline(y, algorithms=None, lam_candidates=None)` — evaluates algorithm/lambda combinations, selects the best result. Default algorithms: all five above. Default lambdas: `[1e3, 1e4, 1e5, 1e6, 1e7]`. Returns `(baseline, info)` where `info` has keys `'algorithm'` (str), `'lam'` (float), `'score'` (float).

## Acceptance criteria

- Each algorithm must satisfy `max|yours − ref| / max|ref| < 5e-3` against pybaselines across multiple synthetic spectra (500- and 1000-point), parameter combinations, and non-default diff orders.
- `diff_penalty_diags` must match the reference to machine precision for orders 1 through 4.
- Parameter validation behavior must match pybaselines (e.g. certain algorithms reject certain diff orders).
- `/app/baseline_engine.py` must not import `pybaselines`.

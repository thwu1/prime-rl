A COCO platform benchmarking experiment is configured at `/app/experiment/`. It evaluates black-box optimizers against a selection of the 24 BBOB noiseless functions across multiple dimensions using the `cocoex` framework. A baseline optimizer is included but performs poorly. Investigate the experiment setup — its configuration, benchmark runner, analysis tools, and the baseline's behavior — to understand why it fails, then build a replacement.

## Required output

Create `/app/optimizer.py` exposing a single function:

```
optimize(func, dim, lb, ub, budget, x0=None) -> (best_x, best_f)
```

- `func`: callable accepting a numpy array, returns a scalar
- `dim`: int, problem dimensionality
- `lb`, `ub`: numpy arrays of lower/upper bounds
- `budget`: int, maximum number of function evaluations
- `x0`: optional initial solution (numpy array)
- Returns a tuple `(best_x, best_f)` where `best_x` is an array-like of length `dim` and `best_f` is a float

## Constraints

The implementation must be original. The following libraries must **not** be imported: `scipy`, `pycma`, `cma`, `nevergrad`, `optuna`, `pymoo`. Only `numpy` and the Python standard library are allowed.

## Verification criteria

### Analytic function convergence

The optimizer is tested on standalone analytic functions (no COCO dependency):

| Function | Dim | Budget | Required best_f |
|---|---|---|---|
| Sphere: `sum(x_i^2)` | 2 | 5,000 | < 1e-8 |
| Sphere | 10 | 20,000 | < 1e-6 |
| Rosenbrock: `sum(100*(x_{i+1} - x_i^2)^2 + (1 - x_i)^2)` | 5 | 50,000 | < 1.0 |
| Ellipsoid: `sum(10^(6i/(D-1)) * x_i^2)` | 5 | 50,000 | < 1e-4 |

All tests use bounds `[-5, 5]^D`.

### BBOB benchmark functions (via `cocoex`)

Each BBOB test runs instances 1–3 and requires a minimum number of instances to hit the COCO final target:

| BBOB Function | ID | Dim | Budget | Min hits (of 3) | Category |
|---|---|---|---|---|---|
| Sphere | f1 | 5 | 100,000 | 3 | Separable |
| Sphere | f1 | 10 | 200,000 | 2 | Separable |
| Separable Ellipsoidal | f2 | 5 | 100,000 | 2 | Separable |
| Rosenbrock (original) | f8 | 5 | 100,000 | 2 | Valley structure |
| Rotated Ellipsoidal | f10 | 5 | 100,000 | 2 | High conditioning (~1e6) |
| Discus | f11 | 5 | 100,000 | 2 | High conditioning (~1e6) |
| Bent Cigar | f12 | 5 | 100,000 | 2 | High conditioning (ridge) |
| Separable Rastrigin | f3 | 2 | 40,000 | 2 | Multimodal |
| Non-separable Rastrigin | f15 | 2 | 40,000 | 1 | Multimodal |

Successfully handling the ill-conditioned functions (f10–f12) requires covariance/directional adaptation; passing the multimodal functions (f3, f15) requires a restart mechanism.
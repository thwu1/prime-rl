The COCO BBOB (Black-Box Optimization Benchmarking) suite constructs benchmark functions from hidden, instance-specific parameters: an optimal solution vector `xopt`, an optimal value `fopt`, and for non-separable functions, orthogonal rotation matrices. The mathematical specifications of the relevant functions and transformations are in `/app/bbob_reference.md`; task configuration is in `/app/config.json`.

Recover these hidden parameters for BBOB functions f1 (Sphere), f2 (Ellipsoidal), f8 (Rosenbrock), and f10 (Rotated Ellipsoidal) — all at dimension 5, instance 1. Then implement standalone evaluation functions that reproduce the COCO function values at arbitrary points using only the recovered parameters. The COCO framework is available via PyPI as `coco-experiment`.

## Deliverables

**`/app/bbob_impl.py`** — A standalone Python module importing only `numpy` and the standard library (no `cocoex`, no `scipy`) that exports:
- `tosz(x)` — the BBOB Tosz non-linear transformation
- `evaluate_f1(x, xopt, fopt)` — Sphere function
- `evaluate_f2(x, xopt, fopt)` — Separable Ellipsoidal function
- `evaluate_f8(x, xopt, fopt)` — Original Rosenbrock function
- `evaluate_f10(x, xopt, fopt, R)` — Rotated Ellipsoidal function

All inputs/outputs are numpy arrays or Python floats.

**`/app/results.json`** — A JSON object keyed by `f1`, `f2`, `f8`, `f10`. Each entry contains:
- `xopt`: recovered optimal solution (D-element array)
- `fopt`: recovered optimal function value (float)
- `condition_number`: condition number of the function at its optimum (float)
- `predictions`: function values at 20 test points (array), computed via `bbob_impl.py` — **not** via cocoex

For `f10` only, an additional field:
- `rotation_matrix`: recovered D x D orthogonal rotation matrix (2D array)

Test points are generated deterministically as `numpy.random.RandomState(42).uniform(-3, 3, (20, 5))`.
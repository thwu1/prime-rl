A Python implementation of the Generalized Moving Peaks Benchmark (GMPB) is at `/app/gmpb.py`. The benchmark generates dynamic fitness landscapes of cone-shaped peaks: `f(x) = max_p [h_p - w_p * ||x - c_p||]`. Peaks shift positions, change heights, and change widths at regular intervals.

Implement a dynamic optimization solver as a multi-component system:

**C Kernel** (`/app/dopt_kernel.c`): A C source file exporting these functions with C linkage:
- `double cone_fitness(const double *x, const double *positions, const double *heights, const double *widths, int num_peaks, int dim)` — Compute `max_p [h_p - w_p * ||x - c_p||]` across all peaks. Positions are stored row-major as `positions[p * dim + d]`.
- `void batch_distances(const double *x, const double *positions, int num_peaks, int dim, double *out)` — Compute Euclidean distance from `x` to each of `num_peaks` peak centers, writing results to `out[p]`.

**Build System** (`/app/Makefile`): Compile `dopt_kernel.c` into `/app/libdopt.so` as a position-independent shared library.

**Python Solver** (`/app/solver.py`): Class `DynamicOptimizer` that loads `/app/libdopt.so` via `ctypes` and uses the C kernel for internal model evaluations (surrogate peak evaluation, archive distance queries).
- `__init__(self, dim: int, bounds: tuple, seed: int = 0)` — Initialize for a `dim`-dimensional search space within `bounds = (lower, upper)`. Build the shared library if absent (via `make`), then load it with `ctypes.CDLL`.
- `optimize_environment(self, eval_fn, budget)` — Optimize within one environment. Call `eval_fn(x)` (where `x` is a numpy array of shape `(dim,)`) up to `budget` times. Higher return values are better. Use the C kernel for internal candidate screening against remembered peak positions.
- `on_change(self)` — Called when the environment changes (peaks shift). The solver must adapt its internal state.

The solver is evaluated by offline error: the mean gap between the true global optimum fitness and the solver's best-found fitness, averaged over every `eval_fn` call across all environments. After each environment change, the solver's best-found value resets internally.

The same solver instance (same `__init__` parameters) must handle all instances below without per-instance tuning.

| Instance | Peaks | Dim | Budget/Env | Shift Severity | Environments | Max Offline Error |
|----------|-------|-----|------------|----------------|--------------|-------------------|
| A        | 10    | 5   | 5000       | 1.5            | 20           | 9.0               |
| B        | 25    | 5   | 5000       | 1.0            | 20           | 10.0              |
| C        | 10    | 5   | 1000       | 2.0            | 20           | 20.0              |
| D        | 10    | 10  | 5000       | 1.5            | 20           | 15.0              |

Read `/app/gmpb.py` to understand the benchmark's fitness function, peak dynamics, evaluation tracking, and offline error computation.
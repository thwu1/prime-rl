A C++ program at `/app/solve_convdiff.cpp` discretizes and solves the 2D steady-state convection-diffusion equation on [0,1]^2 with homogeneous Dirichlet boundary conditions for four parameter configurations spanning different physical regimes. A manufactured exact solution is used to measure accuracy. The build system is at `/app/CMakeLists.txt`; Eigen3 is installed system-wide.

The current implementation applies a single discretization scheme and solver/preconditioner strategy uniformly across all regimes. Build and run it (`mkdir -p /app/build && cd /app/build && cmake .. && make && ./solve_convdiff`) to observe that some configurations produce inaccurate or divergent results.

Modify `/app/solve_convdiff.cpp` so that all four configurations produce accurate, converged results within a reasonable iteration budget. You must analyze each configuration's physical characteristics to determine what is going wrong and adapt the numerical approach accordingly. Document the per-regime analysis and design decisions in `/app/strategy.json`.

**Output file format:**

Each configuration must produce a file `/app/output_1.txt` through `/app/output_4.txt` in `key=value` format (one pair per line). Each file must contain at least these fields: `iterations`, `residual_norm`, `l2_error`, `converged`.

**Numerical acceptance criteria:**

- Every output file must report `converged=true`
- Every output file must have `residual_norm` < 1e-6 (not NaN, not Inf)
- Every output file must have `l2_error` < 0.15 (not NaN, not Inf)
- Combined `iterations` count summed across all four configurations must be < 800

**Strategy file requirements:**

`/app/strategy.json` must contain a top-level `configurations` array with exactly four entries (one per config, covering config IDs 1 through 4). Each entry must have these fields: `config_id` (integer), `grid_peclet_number` (numeric), `discretization` (string describing the discretization method used), `solver` (string), `preconditioner` (string), `rationale` (string providing a substantive justification, more than 20 characters, explaining why that particular approach was chosen for this regime).
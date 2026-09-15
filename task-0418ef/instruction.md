A stiff 1D Brusselator reaction-diffusion PDE (method of lines, 80 coupled ODEs) is set up in `/app/`. A Python reference of the RHS is in `/app/problem.py`; a C implementation is in `/app/rhs_native/brusselator.c` with a Makefile.

Compile the C shared library from `/app/rhs_native/`, then implement a from-scratch ODE solver in Python that integrates this system from t=0 to t=2. The solver must load the compiled C library and call it via `ctypes` for all RHS evaluations during integration.

The solver must produce a final solution accurate to within 10% relative error of a high-order reference. It must exploit the Jacobian's known sparsity structure (available via `problem.sparsity_pattern()`) so that each Jacobian approximation requires fewer RHS evaluations than the system dimension (80). Step sizes must adapt automatically based on local error estimation. The total number of matrix factorizations performed must be strictly fewer than the number of accepted time steps.

`numpy` and `scipy.linalg` may be used. ODE solver libraries (`scipy.integrate`, etc.) are prohibited.

Use `gnuplot` to produce a space-time heatmap of the u-species concentration (grid index on x-axis, time on y-axis), saved as `/app/results/heatmap.png`.

Write all output to `/app/results/`:
- `solution.npz` — arrays `t` (accepted times including t=0, shape `(S,)`) and `y` (state vectors, shape `(S, 80)`)
- `coloring.json` — `{"colors": [c0, ..., c79], "n_colors": <int>}` where each of the 80 Jacobian columns is assigned an integer label; two columns that share a nonzero row in the sparsity pattern must have different labels
- `stats.json` — `{"f_evals": <int>, "jac_evals": <int>, "lu_factorizations": <int>, "steps_accepted": <int>, "steps_rejected": <int>}`
- `step_sizes.csv` — one accepted step size per line
- `heatmap.png` — gnuplot-generated space-time heatmap of u-species
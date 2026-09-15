A numerical pipeline in `/app/` solves a 1D advection-diffusion PDE on a non-uniform periodic grid and produces stability analysis results. It combines a C shared library (`libfdweights.c` compiled to `libfdweights.so`) for finite difference weight computation with a Python driver (`solver.py`) for matrix assembly, eigenvalue analysis, time integration, and error measurement.

Run `python3 /app/solver.py` — the results are numerically incorrect. Debug and fix all numerical issues across both the C and Python code so that `/app/results.json` is produced with correct values. The configuration is in `/app/config.json`.

## Output schema

`/app/results.json` must be a JSON object containing exactly these keys:

- `spectral_radius` (float): max |lambda_i| over all eigenvalues of the spatial operator L.
- `dt_max_forward_euler` (float): the largest time step for which the Forward Euler method is stable given the eigenvalue spectrum of L. Must be positive.
- `dt_max_rk4` (float): the largest time step for which Classical RK4 is stable given the eigenvalue spectrum of L. Must be positive and larger than `dt_max_forward_euler`.
- `rk4_simulation_l2_error` (float): RMS error sqrt(mean((u_num - u_exact)^2)) at final time. Must be positive, below 5e-3, and plausible for a 4th-order method on the configured grid (between 1e-10 and 1e-2).
- `eigenvalues_real` (array of N floats): real parts of all N eigenvalues of L, sorted by magnitude ascending.
- `eigenvalues_imag` (array of N floats): imaginary parts of all N eigenvalues of L, sorted by magnitude ascending.
- `fd_weights_d1_at_j32` (array of 5 floats): 1st derivative FD weights at grid point j=32 for the 5-point stencil.
- `fd_weights_d2_at_j32` (array of 5 floats): 2nd derivative FD weights at grid point j=32 for the 5-point stencil.

## Correctness criteria

- All eigenvalues of the spatial operator must have non-positive real parts.
- The reported `spectral_radius` must equal the maximum magnitude of the reported eigenvalues (self-consistent to relative error < 1e-6).
- Eigenvalues, spectral radius, and both stability limits must match an independently computed reference within tight tolerances (0.1% for eigenvalues/spectral radius, 2% for stability limits).
- The FD weights at j=32 must exactly differentiate polynomials x^0 through x^4 (polynomial exactness up to the stencil's design order), and must match correct weights for the non-uniform grid within 1e-8.
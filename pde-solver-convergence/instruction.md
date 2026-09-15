Implement numerical PDE solvers for three problems specified in `/app/problems.json`, verify their accuracy against known analytic solutions, and demonstrate correct convergence rates via grid-refinement studies.

The three problems span different PDE types requiring different numerical approaches: a variable-coefficient drift-diffusion equation (Fokker-Planck/Ornstein-Uhlenbeck), a dispersive nonlinear wave equation (focusing cubic NLS with soliton solution), and an indefinite elliptic equation (2D Helmholtz with k^2 exceeding the first Laplacian eigenvalue).

Write results to `/app/results.json` keyed by problem ID (`fokker_planck_ou`, `nls_soliton`, `helmholtz_2d`). Each entry must contain:
- `l2_error`: root-mean-square error at the finest resolution
- `convergence_rate`: estimated spatial convergence order from the two finest resolutions
- `convergence_study`: list of `{"resolution": N, "l2_error": e}` at 3+ resolutions (each ~2x the previous)

Save numerical solutions as NumPy `.npz` archives in `/app/solutions/` for independent verification:
- `fokker_planck_ou.npz` — keys: `u` (1D solution at t=1), `x` (spatial grid of interior points)
- `nls_soliton.npz` — keys: `psi` (complex 1D solution at t=pi), `x` (spatial grid), `mass_initial` (float), `mass_final` (float)
- `helmholtz_2d.npz` — keys: `u` (2D solution array), `x` (1D x-coordinates of interior points), `y` (1D y-coordinates of interior points)

The NLS solver must conserve the L2 norm (mass) to within relative error 1e-4. The Fokker-Planck solution must remain non-negative. Convergence rates must fall within the range expected for the chosen scheme's theoretical order.
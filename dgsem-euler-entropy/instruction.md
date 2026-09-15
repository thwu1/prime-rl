Implement a high-order nodal discontinuous Galerkin spectral element method (DGSEM) for the 1D compressible Euler equations and verify its entropy-conservation and summation-by-parts (SBP) properties. The spatial discretization must use polynomial degree >= 3 with a diagonal-norm SBP operator derived from Legendre-Gauss-Lobatto quadrature. The volume term must employ entropy-conservative flux differencing to achieve semi-discrete entropy conservation.

The governing equations are dU/dt + dF(U)/dx = 0 with U = [rho, rho*v, E], F = [rho*v, rho*v^2+p, (E+p)*v], and p = (gamma-1)(E - 0.5*rho*v^2), gamma = 1.4.

Produce the following outputs:

## `/app/results/sod.csv`

Sod shock tube on domain [0,1], 64 uniform elements, polynomial degree 3, t_final = 0.2. Left state (x<0.5): (rho,v,p)=(1,0,1); right state: (0.125,0,0.1). Fixed (non-reflecting) boundary conditions holding initial boundary values. CSV columns: `x,rho,v,p` — cell-averaged primitive variables at element centers sorted by x, 64 rows.

## `/app/results/entropy.json`

Smooth periodic advection on [0,1], 16 elements, degree 4, periodic boundaries, t_final = 2.0. Initial conditions: rho = 1+0.5*sin(2*pi*x), v = 1, p = 1. Both volume and surface numerical fluxes must be entropy-conservative (no dissipation). Compute total mathematical entropy S = integral[-rho*s/(gamma-1)] dx where s = ln(p) - gamma*ln(rho). JSON keys: `S_initial`, `S_final`, `S_change` (= S_final - S_initial). Require |S_change| < 1e-4.

## `/app/results/spectral.json` (via GNU Octave)

For polynomial degree N=5, export the reference-element diagonal mass matrix M (6x6) and derivative matrix D (6x6) to `/app/results/mass_matrix.csv` and `/app/results/deriv_matrix.csv`. An Octave script (`/usr/bin/octave`) must independently load these matrices and write `/app/results/spectral.json` with keys:

- `sbp_error`: Frobenius norm of (Q+Q^T-B) where Q=M*D and B=diag(-1,0,...,0,1). Must be < 1e-10.
- `mass_cond`: condition number of M.
- `D_spectral_radius`: max |eigenvalue(D)|.
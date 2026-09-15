Implement a finite volume solver for the 1D compressible Euler equations and use it to solve the Sod shock tube problem. The solution must capture the correct wave structure: a left-moving rarefaction fan, a contact discontinuity, and a right-moving shock wave.

**Solver specifications:**
- HLLC approximate Riemann solver for intercell flux computation
- MUSCL reconstruction with van Albada slope limiter on primitive variables (rho, u, p) for 2nd-order spatial accuracy
- 2nd-order TVD Runge-Kutta time integration (Shu-Osher method)
- CFL number = 0.5
- Transmissive (zero-gradient) boundary conditions

**Problem definition (Sod shock tube):**
- Domain: [0, 1], N = 400 uniform cells, gamma = 1.4
- Left state (x < 0.5): rho = 1.0, u = 0.0, p = 1.0
- Right state (x >= 0.5): rho = 0.125, u = 0.0, p = 0.1
- Integrate to final time t = 0.2

**Required output:**

`/app/results.json` containing:
- `shock_position`: x-coordinate of the shock wave (steepest rightward density gradient)
- `contact_position`: x-coordinate of the contact discontinuity
- `post_shock_density`: mean density between contact and shock
- `post_shock_pressure`: mean pressure between contact and shock
- `star_velocity`: flow velocity in the star region (plateau between rarefaction tail and shock)
- `density_l2_error`: L2 norm sqrt(dx * sum((rho_numerical - rho_exact)^2)) computed against the exact Riemann solution
- `total_mass`: integrated density (sum of rho * dx over all cells)
- `n_cells`: 400

`/app/solution.csv` with header `x,rho,u,p` and one row per cell (400 rows total).

Computing `density_l2_error` requires implementing the exact Riemann solver (Newton iteration for the star-state pressure, then sampling the self-similar solution).
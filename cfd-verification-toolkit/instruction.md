A partial CFD verification pipeline at `/app/` needs to be completed. Input data:

- `/app/data/ci2_init_legacy.py` — Python 2 initial condition generator for the HiOCFD5 CI2 vortex-shock interaction benchmark
- `/app/data/convergence_data.csv` — grid refinement study (mesh spacing `h` vs. lift coefficient `CL`)
- `/app/data/channel.geo` — Gmsh geometry file for the CI2 domain [0,1]x[0,1]

Produce these output files:

## `/app/results/verification_results.json`

JSON with this structure:

**`compressible.normal_shock`** — Downstream flow state for a stationary normal shock at upstream Mach 1.5 in a calorically perfect gas (gamma=1.4). Keys: `M2`, `p2_p1`, `rho2_rho1`, `T2_T1`, `p02_p01`.

**`compressible.isentropic`** — Static-to-stagnation property ratios at Mach 2.0, gamma=1.4. Keys: `p_p0`, `T_T0`, `rho_rho0`, `A_Astar`.

**`ci2`** — Flow state from the legacy script (ported to Python 3) at three probes: `upstream_freestream` at (0.05, 0.90), `downstream_postshock` at (0.60, 0.50), `vortex_inner` at (0.20, 0.55). Each contains `pressure`, `temperature`, `velocity_x`, `velocity_y`.

**`convergence`** — Grid convergence analysis of the CSV data. Keys: `observed_orders` (convergence rates from consecutive grid-level triples), `extrapolated_value` (grid-independent value extrapolated from the two finest levels using the finest observed rate), `uncertainty_fine` (fine-grid convergence uncertainty, safety factor 1.25).

**`mms`** — Forcing terms that make the following analytical state an exact steady solution of the 2D compressible Euler equations (gamma=1.4): rho = 1 + 0.1*sin(2*pi*x)*cos(2*pi*y), u = 0.5 + 0.05*sin(2*pi*x), v = 0.3 + 0.05*cos(2*pi*y), p = 1 + 0.2*sin(2*pi*x)*cos(2*pi*y). Keys: `source_at_test_point` with `S_mass`, `S_xmom`, `S_ymom`, `S_energy` at (0.25, 0.25); `max_residual` — maximum self-consistency error across a 50x50 uniform grid on [0,1]^2.

## `/app/results/ci2_solution.msh`

Mesh `/app/data/channel.geo` using Gmsh, evaluate the CI2 initial condition at every mesh node, and export as a Gmsh MSH file with per-node fields: `pressure`, `temperature`, `velocity_x`, `velocity_y`.
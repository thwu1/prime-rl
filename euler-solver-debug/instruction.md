A simulation pipeline for 1D compressible gas dynamics is at `/app/`. It consists of:
- `mesh_template.geo` — a gmsh geometry script for generating 1D meshes
- `euler_solver.py` — a Kurganov-Tadmor finite volume solver that reads gmsh `.msh` meshes
- `exact_riemann.py` — stub for an exact Riemann solver (Newton-Raphson iteration, wave sampling)
- `run_study.py` — incomplete convergence study orchestrator
- `problem_config.json` — defines a custom Riemann problem for an ideal gas
- `plot_convergence.gp` — skeleton gnuplot convergence plot script

The numerical solver contains bugs that produce incorrect results or divergence. The gmsh geometry script has defects preventing proper mesh generation and export. The exact Riemann solver, convergence study runner, and gnuplot script are incomplete.

Fix all bugs, implement the missing components, and run a grid convergence study at N = 100, 200, 400, 800 cells. Use `gmsh` to generate meshes at each resolution, the corrected solver to compute numerical solutions, the exact Riemann solver for analytical reference, and `gnuplot` to produce a log-log convergence plot.

Compute observed convergence order via Richardson extrapolation and Grid Convergence Index (GCI) with Roache's method (Fs = 1.25).

Write results to `/app/results.json` containing: `p_star`, `u_star`, `rho_star_L`, `rho_star_R`, `shock_speed`, `contact_speed`, `rarefaction_head_speed`, `rarefaction_tail_speed`, `convergence_order`, `gci_finest`, `l2_error_density_N100`, `l2_error_density_N200`, `l2_error_density_N400`, `l2_error_density_N800`.

Mesh files must be at `/app/mesh_N{100,200,400,800}.msh`. Convergence data at `/app/convergence_data.dat`. Convergence plot at `/app/convergence.png`.
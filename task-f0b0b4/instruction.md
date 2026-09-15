Grid convergence studies from two NASA flow solvers (CFL3D and FUN3D) on a zero-pressure-gradient flat plate are in `/app/data/`. Both use the Spalart-Allmaras turbulence model with nominally 2nd-order finite-volume discretization (M=0.2, Re_L=5×10⁶ per unit length, L=2). Five grid levels with refinement ratio 2 are provided per solver.

Data files (multi-zone Tecplot ASCII):
- `cf_convergence.dat` — Cf at x=0.97 across grids. Columns: N, h², h, Cf
- `drag_convergence.dat` — Integrated drag CD across grids. Same layout
- `flatplate_u.dat` — Velocity profile (u/U∞, y/L) at x=0.97, finest grid
- `flatplate_uplus_yplus.dat` — Wall-scaled profile (log₁₀y⁺, u⁺) at x=0.97, finest grid

Assess whether these results are publication-ready and produce:

**`/app/report.json`** with the following keys:

- `grid_convergence` — For each of `cf_cfl3d`, `cf_fun3d`, `cd_cfl3d`, `cd_fun3d`: `observed_order` (apparent spatial convergence rate), `fine_grid_uncertainty_pct` (numerical uncertainty on the finest grid, as a percentage), `extrapolated_value` (estimate at vanishing grid spacing), and `order_verdict` — `"nominal"` if order ≥ 1.5, `"degraded"` if ≥ 0.5, `"anomalous"` otherwise.

- `solver_ranking` — For `skin_friction` and `drag` separately: which solver (`"cfl3d"` or `"fun3d"`) achieves lower fine-grid uncertainty.

- `boundary_layer` — From the velocity profile: `delta_99`, `displacement_thickness`, `momentum_thickness`, `shape_factor`, `re_theta` (using Re_L), `wall_cf` (from the near-wall velocity gradient). `physically_consistent`: true only if shape_factor ∈ [1.2, 1.5].

- `wall_law_fit` — Assess the wall-scaled profile against the analytical law of the wall in the log-linear region (30 < y⁺ < 300). Report `rms_deviation` and `max_deviation` in log₁₀(y⁺) space, `num_points` evaluated, and `log_layer_quality`: `"excellent"` if RMS < 0.02, `"good"` if < 0.05, `"acceptable"` if < 0.10, `"poor"` otherwise.

- `publication_ready` — For each solver-quantity case: true if fine-grid uncertainty < 1% and observed order ≥ 0.5.

**`/app/plot_cf.svg`** and **`/app/plot_cd.svg`** — Grid convergence plots generated with gnuplot, each showing both solvers as distinct series with labeled axes.
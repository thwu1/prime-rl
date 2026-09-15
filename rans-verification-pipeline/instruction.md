NASA Turbulence Modeling Resource (TMR) data files for the 2D zero-pressure-gradient flat plate case (SA turbulence model, M=0.2, Re=5M) are provided in `/data/`. The dataset includes grid convergence results from two independent CFD codes (CFL3D and FUN3D), velocity profiles, eddy viscosity profiles, a PLOT2D-format structured grid, and law-of-the-wall reference curves.

Write `/app/analysis.py` to read the data files and produce `/app/results.json` containing the following top-level keys:

**`gci_analysis`** — Grid convergence study using the three finest grids. For each of `skin_friction` and `drag`, provide sub-keys `cfl3d` and `fun3d`, each containing: `apparent_order`, `extrapolated_value`, `fine_grid_value`, `relative_error_percent`, `gci_fine_percent`.

**`boundary_layer`** — Boundary layer integral quantities from the velocity profile at x=0.97: `u_edge`, `delta_99`, `displacement_thickness`, `momentum_thickness`, `shape_factor`.

**`sa_model`** — Standard SA turbulence model auxiliary function evaluations: `fv1_at_chi_1`, `fv1_at_chi_10`, `fv2_at_chi_1`, `fv2_at_chi_10`, `fw_at_r_0p5`, `fw_at_r_1`, `cw1`. From the eddy viscosity profile at x=0.97: `peak_mut_over_mu_inf`, `y_at_peak_mut`.

**`law_of_wall`** — Composite law-of-the-wall fit to the u+/y+ profile data: `kappa`, `B`, `rms_log_deviation` (RMS of log10(y+\_predicted) - log10(y+\_data)).

**`grid_metrics`** — PLOT2D grid file analysis: `nx`, `ny`, `x_range` [min, max], `y_range` [min, max], `first_cell_height` (wall-normal spacing of first cell at the first on-plate grid point), `max_wall_normal_stretching_ratio` (maximum ratio of consecutive wall-normal cell spacings on the plate).
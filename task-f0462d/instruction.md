A 400m x 400m x 200m subsurface volume has been discretized into 32 rectangular prisms (4x4x2 grid). Vertical gravitational acceleration (`g_u`) was measured at 64 surface stations above the volume. The measurements were generated from a synthetic ground-truth density model. Your task: recover the density distribution, validate the physical consistency of your gravitational forward model, report inversion diagnostics, and produce a visualization of the result.

## Input Data

- `/app/problem_config.json` — Prism boundaries (each `[west, east, south, north, bottom, top]` in meters), gravitational constant `G`, Laplace verification test point coordinates, grid dimensions, and prism indexing convention (`index = iz * ny * nx + iy * nx + ix`).
- `/app/observed_gravity.json` — Measured `g_u` values at 64 observation points in SI units (m/s²). All coordinates use the easting-northing-upward convention.

## Required Outputs

### `/app/recovered_densities.json`
JSON with key `"densities"`: a list of 32 floats (kg/m³), one per prism in the same order as `prisms` in the config.

Evaluation criteria (applied against the ground-truth synthetic model):
- Overall RMSE < 30 kg/m³
- Prisms with true density = 0: |recovered| < 50 kg/m³
- Prisms with non-zero true density: relative error < 10%
- Forward-predicted `g_u` from recovered densities must fit observed data with normalized RMS (`rms_residual / max|g_u_observed|`) < 1%

### `/app/laplace_verification.json`
JSON with key `"results"`: a list of objects, one per point in `laplace_test_points` from the config. Each object must contain:
- `"g_ee"`, `"g_nn"`, `"g_uu"`: diagonal components of the gravity gradient tensor (second spatial derivatives of the gravitational potential, in 1/s²), computed from all prisms using the recovered densities
- `"laplace_residual"`: the sum `g_ee + g_nn + g_uu`

Requirement: at every test point, `|g_ee + g_nn + g_uu| / max(|g_ee|, |g_nn|, |g_uu|)` must be < 1e-6.

### `/app/inversion_diagnostics.json`
JSON containing:
- `"condition_number"`: condition number of the forward-modeling sensitivity matrix (positive float)
- `"data_rms_misfit"`: RMS misfit between forward-predicted and observed data in m/s² (non-negative float)
- `"n_observations"`: integer, must equal 64
- `"n_parameters"`: integer, must equal 32

### `/app/density_model.png`
PNG image visualizing the recovered density distribution across the prism grid (e.g., color-coded cross-sections per depth layer). Generate this using `gnuplot`, which is available at `/usr/bin/gnuplot` in the environment.

## Constraints

- No external geophysics or potential-field modeling packages may be used
- NumPy and SciPy are permitted for numerical linear algebra
- All coordinates use the easting-northing-upward sign convention
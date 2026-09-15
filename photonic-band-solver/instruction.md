Implement `/app/solve_bands.py`, `/app/optimize_gap.py`, and `/app/convergence.py` to compute 2D photonic crystal TM-polarized band structures. These tools must be self-contained — no external electromagnetic simulation packages (meep, mpb, lumerical, comsol); only general-purpose numerical libraries (numpy, scipy) are permitted.

Material dielectric constants must be resolved by name from the database at `/app/data/materials.json`. Reference band-gap data from high-resolution MPB computations is available in `/app/data/reference/`; the format of these files is not specified here — scripts must parse them to extract validation targets.

### `/app/solve_bands.py <config.json>`

Config schema:
```json
{
  "lattice_type": "square" | "triangular",
  "rod_material": "<material_name>",
  "background_material": "<material_name>",
  "radius": float,
  "num_bands": int,
  "resolution": int,
  "k_interp": int
}
```

Material names are resolved to dielectric constants via `/app/data/materials.json`. `radius` in units of lattice constant *a*; frequencies in *c/a*. `resolution` controls the Fourier truncation order. IBZ path: square Gamma-X-M-Gamma; triangular Gamma-M-K-Gamma, with `k_interp` interpolation points between consecutive vertices (must produce at least 15 total k-points).

Output `/app/results.json`:
```json
{
  "bands": [[f1, f2, ...], ...],
  "gaps": [{"from_band": int, "to_band": int, "gap_min": float, "gap_max": float, "gap_percent": float}]
}
```

`bands[i][j]` = frequency of band `j+1` at k-point `i`. `gap_min` = max of lower band over all k. `gap_max` = min of upper band over all k. `gap_percent` = 200*(gap_max - gap_min)/(gap_max + gap_min). Only report gaps exceeding 1%.

### `/app/optimize_gap.py <config.json>`

Same config schema as above, plus `radius_min` and `radius_max` (floats); omit `radius`. Finds the rod radius maximizing the first TM gap (bands 1 to 2).

Output `/app/opt_result.json`:
```json
{"optimal_radius": float, "max_gap_percent": float}
```

### `/app/convergence.py <config.json>`

Same config schema as `solve_bands`, plus `target_accuracy` (float, relative error threshold) and `reference_file` (path to a reference data file in `/app/data/reference/`). Determines the minimum `resolution` parameter at which the first TM gap percentage converges to within `target_accuracy` of the reference value parsed from the reference file. The `resolution_series` must contain results for at least 5 resolution values tested, starting from resolution 4.

Output `/app/convergence_result.json`:
```json
{
  "min_resolution": int,
  "converged_gap_percent": float,
  "reference_gap_percent": float,
  "relative_error": float,
  "resolution_series": [{"resolution": int, "gap_percent": float, "error": float}]
}
```

### Accuracy

With `resolution=20`, `k_interp=4`: band gap percentages within 5 percentage points of reference values; band edge frequencies within 5% relative error of reference values. Optimizer must find optimal radius within 0.02 of reference optimum.

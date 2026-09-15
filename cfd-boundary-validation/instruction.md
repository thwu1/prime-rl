You are given experimental wind tunnel velocity profile data and CFD simulation results on systematically refined grids. Produce `/app/results.json` — a complete Verification & Validation report for a turbulent boundary layer flow case.

## Data

All input data is in `/app/data/`:

- `rake_re250k.dat`, `rake_re650k.dat` — Boundary layer rake velocity profiles at Re_H = 250,000 and 650,000. Tab-separated columns: `y/H` and `U/U_inf`. Flow conditions and geometry in file headers.
- `piv_re250k.dat`, `piv_re650k.dat` — PIV velocity profiles at the same Reynolds numbers. Higher near-wall resolution than the rake data.
- `grid_convergence.csv` — CFD results (Cd, Cf_crest, Cp_te) on 5 systematically refined grids for a 2D bump-in-channel case.
- `reference_conditions.json` — Flow conditions, geometry parameters, and analysis constants.

## Required Output

Write `/app/results.json` with this exact structure (all numeric values as floats):

```json
{
  "boundary_layer": {
    "re250k": {"delta_star": ..., "theta": ..., "H": ...},
    "re650k": {"delta_star": ..., "theta": ..., "H": ...}
  },
  "skin_friction": {
    "re250k": {"u_tau": ..., "Cf": ...},
    "re650k": {"u_tau": ..., "Cf": ...}
  },
  "grid_convergence": {
    "Cd": {"convergence_type": "monotonic"|"oscillatory", "observed_order": ..., "f_extrapolated": ..., "GCI_fine": ...},
    "Cf_crest": {"convergence_type": "monotonic"|"oscillatory", "observed_order": ..., "f_extrapolated": ..., "GCI_fine": ...},
    "Cp_te": {"convergence_type": "monotonic"|"oscillatory"}
  }
}
```

**boundary_layer**: For each Reynolds number, compute displacement thickness (δ\*), momentum thickness (θ), and shape factor (H = δ\*/θ) from the rake velocity profiles.

**skin_friction**: For each Reynolds number, determine friction velocity (u_τ) and skin friction coefficient (Cf) from the PIV velocity profiles. Use the constants and flow conditions in `reference_conditions.json`.

**grid_convergence**: For each quantity across the grid hierarchy, classify convergence behavior. For monotonically convergent quantities, report the observed order of accuracy, the grid-independent extrapolated value, and the fine-grid discretization uncertainty estimate (GCI_fine). For oscillatory convergence, report only `convergence_type` and omit the other fields. Analysis parameters are in `reference_conditions.json`.
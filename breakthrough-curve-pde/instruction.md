Five experimental breakthrough curves for Pb2+ adsorption on activated carbon are at `/app/data/curve_A.csv` through `/app/data/curve_E.csv`. Each CSV has a metadata header line with operating conditions (`key=value` format), followed by `time_min,C_over_C0` data columns. Column physical properties and Langmuir isotherm parameters are in `/app/column_params.json`.

Create `/app/analyze.py`. Running `python3 /app/analyze.py` must produce `/app/results.json` with this structure (all values float):

```json
{
  "yoon_nelson": {"<A-E>": {"k_YN": 0, "tau": 0, "R2": 0, "k_YN_ci95": [0,0], "tau_ci95": [0,0]}},
  "thomas": {"<A-E>": {"k_Th": 0, "q_0": 0, "R2": 0}},
  "adams_bohart": {"<A-E>": {"k_AB": 0, "N_0": 0, "R2": 0}},
  "capacity": {"<A-E>": {"q_exp_mg_g": 0}},
  "mtz": {"<A-E>": {"t_b": 0, "t_e": 0, "H_MTZ_cm": 0, "f_b": 0}},
  "bdst": {"slope": 0, "intercept": 0, "N_0": 0, "k_a": 0, "Z_0": 0},
  "pde_model": {
    "calibration": {"k_LDF": 0, "q_max_mg_g": 0, "R2": 0, "RMSE": 0},
    "validation": {"<B-E>": {"R2": 0, "RMSE": 0}}
  },
  "sensitivity": {
    "k_LDF_plus20": {"R2": 0, "RMSE": 0},
    "k_LDF_minus20": {"R2": 0, "RMSE": 0},
    "q_max_plus20": {"R2": 0, "RMSE": 0},
    "q_max_minus20": {"R2": 0, "RMSE": 0}
  }
}
```

**Units and conventions:**

- `k_YN`: 1/min. `tau`: min. `k_YN_ci95`, `tau_ci95`: 95% confidence intervals.
- `k_Th`: mL/(mg*min). `q_0`: mg/g. Bed mass derived from bulk density and bed geometry.
- `k_AB`: L/(mg*min). `N_0`: mg/L. Fit only data where C/C0 < 0.15.
- `q_exp_mg_g`: experimental adsorption capacity (mg/g) from mass balance integration of each curve.
- Breakthrough defined at C/C0 = 0.05 (0 if initial value already exceeds this). Exhaustion at C/C0 = 0.95. Both via linear interpolation. `H_MTZ_cm`: mass transfer zone height. `f_b`: fractional bed utilization up to breakthrough.
- BDST: identify curves with identical C0 and flow rate but differing bed heights. Derive the bed-depth vs. service-time relationship from breakthrough times at C/C0 = 0.05. `N_0`: mg/L, `k_a`: L/(mg*min), `Z_0`: critical bed depth (cm). Use superficial velocity.
- PDE: 1D fixed-bed column with axial dispersion, mass transfer kinetics, and Langmuir equilibrium from `column_params.json`. Calibrate `k_LDF` (1/s) and `q_max` (mg/g) against Curve A. Validate on B-E with frozen kinetics, updating only operating conditions and transport properties. R2 and RMSE of C/C0 for each.
- Sensitivity: independently perturb calibrated `k_LDF` and `q_max` by +/-20%, re-simulate Curve A, report resulting R2 and RMSE.

Must complete within 5 minutes.

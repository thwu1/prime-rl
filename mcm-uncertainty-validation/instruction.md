A calibration laboratory has stored measurement parameters for a microwave comparison loss experiment in a SQLite database at `/app/input/calibration.db`.

**Database schema:**
- `calibration_cases` — columns: `case_id INTEGER`, `x1 REAL`, `x2 REAL`, `u1 REAL`, `u2 REAL`, `r REAL` — six scenarios specifying input quantity estimates, standard uncertainties, and correlation coefficient for a bivariate Gaussian joint distribution
- `analysis_config` — columns: `key TEXT`, `value_real REAL` — contains entries `coverage_probability` and `ndig`

The measurement model is `delta_Y = X1^2 + X2^2`, where `(X1, X2)` are jointly Gaussian input quantities parameterized per case in the database.

Determine whether the GUM linearized uncertainty framework produces valid uncertainty estimates for this model across all stored scenarios, following the methodology of JCGM 101:2008 (*Evaluation of measurement data — Supplement 1 to the GUM — Propagation of distributions using a Monte Carlo method*).

Produce the following output files:

**`/app/results/comparison_loss.json`** — Results for each scenario, keyed `"case_1"` through `"case_6"`:

```json
{
  "case_N": {
    "mcm": {"y": float, "u_y": float, "shortest_95": [lo, hi], "symmetric_95": [lo, hi], "M_trials": int},
    "guf1": {"y": float, "u_y": float, "coverage_95": [lo, hi]},
    "guf2": {"y": float, "u_y": float, "coverage_95": [lo, hi]},
    "validation": {"ndig": int, "delta": float, "d_low": float, "d_high": float, "validated": bool}
  }
}
```

- `mcm`: adaptive Monte Carlo simulation results — point estimate, standard uncertainty, shortest and probabilistically symmetric coverage intervals at the configured probability, and total trial count
- `guf1` / `guf2`: first-order and second-order GUM uncertainty framework results with Gaussian coverage
- `validation`: whether GUF1 coverage endpoints agree with MCM shortest coverage endpoints within the numerical tolerance for the configured `ndig`

**`/app/results/convergence.svg`** — Diagnostic plot (SVG format) showing how the Monte Carlo running estimate and standard uncertainty converge as trial count increases, for at least cases 1 and 3.
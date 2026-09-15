You are a CFD post-processing engineer preparing the ensemble analysis for the 8th AIAA Drag Prediction Workshop (DPW-8). Six independent solver teams submitted force and moment coefficients for the NASA Common Research Model (CRM) Wing/Body configuration at M=0.85, Re_c=5x10^6.

## Data

- `/app/data/solver_results.h5` — HDF5 file containing all solver submissions. Each top-level group is a solver ID (e.g., `S001`). Group attributes store solver metadata (`solver_name`, `turbulence_model`, `grid_level`, `grid_size`). Each group has a `polar` subgroup with datasets `alpha`, `CL`, `CD`, `CM`. Three solvers also have a `grid_convergence` subgroup with multi-level grid study data (datasets `grid_level`, `grid_size`, `CL`, `CD`, `CM`; attribute `alpha` gives the angle of attack).

- `/app/data/experimental.csv` — Wind tunnel force/moment data with measurement uncertainties (95% CI). Has comment lines starting with `#` and a header row.

- `/app/data/reference.toml` — CRM reference geometry parameters, freestream conditions, and submission format requirements.

- `/app/data/dpw8_template.dat` — The official DPW-8 31-column Tecplot ASCII force/moment submission template. This defines the exact variable names, column ordering, metadata conventions, and formatting that the output submission file must follow.

## Required Output

Produce the following three files:

### 1. `/app/output/ensemble.db` — SQLite database

Tables required:

- **`solvers`**: columns `solver_id TEXT PRIMARY KEY, solver_name TEXT, turbulence_model TEXT, grid_level INTEGER, grid_size INTEGER`
- **`coefficients`**: columns `solver_id TEXT, alpha REAL, CL REAL, CD REAL, CM REAL`
- **`statistics`**: per-alpha ensemble statistics from *accepted* solvers only — columns `alpha REAL, CL_mean REAL, CL_std REAL, CD_mean REAL, CD_std REAL, CM_mean REAL, CM_std REAL, n_solvers INTEGER`
- **`outliers`**: flagged submissions — columns `solver_id TEXT, reason TEXT`
- **`grid_convergence`**: continuum-limit estimates per solver — columns `solver_id TEXT, CL_h0 REAL, CD_h0 REAL, CM_h0 REAL, order_CL REAL, order_CD REAL, order_CM REAL`
- **`validation`**: experimental comparison using accepted-solver statistics — columns `alpha REAL, CL_exp REAL, CL_comp REAL, CL_delta REAL, CD_exp REAL, CD_comp REAL, CD_delta REAL, within_uncertainty INTEGER` (1 if all three coefficients fall within experimental uncertainty at that alpha, 0 otherwise)

One solver's results are anomalous and should be identified, flagged in the `outliers` table, and excluded from the `statistics` and `validation` tables. The standard deviation in `statistics` should use Bessel's correction (sample std, N-1 denominator).

### 2. `/app/output/ensemble_submission.dat` — DPW-8 Tecplot submission file

A valid Tecplot ASCII file following the format in `/app/data/dpw8_template.dat`. It must contain the ensemble-averaged results (from accepted solvers only) with participant ID `ENS.01`. Include one zone with the polar data (all alpha values at a single representative grid level). Use -999 for any optional columns not available.

### 3. `/app/output/analysis.json` — Summary

```json
{
  "n_solvers_total": <int>,
  "n_solvers_accepted": <int>,
  "outlier_ids": [<list of rejected solver IDs>],
  "ensemble_cl_at_alpha_2": <float>,
  "ensemble_cd_at_alpha_2": <float>,
  "continuum_estimates": {
    "<solver_id>": {"CL_h0": <float>, "order": <float>},
    ...
  }
}
```
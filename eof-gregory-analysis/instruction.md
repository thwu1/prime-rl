A climate modeling group has analyzed coupled model output using the multi-stage pipeline at `/app/pipeline/`. The pipeline's entry point is `/app/pipeline/run_analysis.sh`, which orchestrates data preprocessing and statistical analysis of the NetCDF dataset at `/app/data/climate_output.nc` (variable descriptions at `/app/data/README.txt`). The pipeline chains shell-based climate data operators and Python analysis scripts. Its pre-computed output is at `/app/pipeline/results_original.json`.

An external review has flagged the results as physically inconsistent with the simulated system. The pipeline contains multiple methodological errors distributed across its shell and Python components that corrupt the results. Audit the entire pipeline, identify the errors, and produce a corrected analysis.

Write corrected results to `/app/results.json`:
- `n_significant_modes` (int): number of statistically significant variability modes
- `mode_periods` (list of float): dominant oscillation period for each significant mode, sorted ascending
- `explained_variance_pct` (list of float): percent variance for each significant mode, descending order
- `ecs_estimate` (float): equilibrium climate sensitivity in Kelvin
- `feedback_parameter` (float): climate feedback parameter in W/m²/K
- `total_variance_explained_pct` (float): total percent variance across all significant modes

Write an audit report to `/app/audit.json`:
- `errors_found` (list of objects, each with `category` string and `description` string): methodological errors identified in the pipeline
- `n_errors` (int): number of distinct errors found
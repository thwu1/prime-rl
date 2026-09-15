`/app/data/hudson_bay_pelts.csv` contains annual fur pelt trading records (in thousands) for two wildlife species from the Hudson Bay Company, 1900-1920.

Analyze the dataset to determine the ecological relationship between the two species and the mechanism driving their population fluctuations. Build a Bayesian mechanistic model that captures this relationship, fit it, and produce 10-year forward population forecasts (1921-1930). Explore `/opt/` for available computational tools.

Convergence requirements: all parameter R-hat < 1.1, all bulk ESS > 50, total divergent transitions < 500.

Required outputs:

- `/app/models/dynamics.stan` -- model source
- `/app/results/posterior_summary.json` -- posterior summaries for all model parameters:
  ```json
  {
    "parameters": {
      "<param_name>": {"mean": ..., "q5": ..., "q95": ..., "rhat": ..., "ess_bulk": ...},
      ...
    },
    "diagnostics": {
      "total_divergent_transitions": ...,
      "max_rhat": ...,
      "min_ess_bulk": ...
    }
  }
  ```
- `/app/results/posterior_predictive.csv` -- 20 rows (1901-1920), columns: `year,hare_mean,hare_q5,hare_q95,lynx_mean,lynx_q5,lynx_q95`
- `/app/results/predictions.csv` -- 10 rows (1921-1930), same column format
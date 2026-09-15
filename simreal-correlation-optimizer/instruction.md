A robotics study evaluated 8 manipulation policies across 5 tasks under 4 simulation environment variants plus real-world conditions. The evaluation data is distributed across multiple sources in `/app/data/`:

- `sim/` — one CSV file per simulation variant (columns: `policy`, `task`, `success_rate`)
- `real_results.csv` — real-world success rates (columns: `policy`, `task`, `success_rate`)
- `experiment.db` — SQLite database with trial count metadata and analysis configuration parameters

Produce `/app/results.json` with the following structure:

```json
{
  "mmrv_scores": {"<policy>": float, ...},
  "real_mean_scores": {"<policy>": float, ...},
  "task_correlations": {"<task>": float, ...},
  "fisher_z_mean_r": float,
  "anova_eta_squared": {"policy": float, "task": float, "variant": float},
  "anova_f_stats": {"policy": float, "task": float, "variant": float},
  "deming_calibration": {"<variant>": {"slope": float, "intercept": float}, ...},
  "influence_diagnostics": {"<policy>": {"leverage": float, "cooks_d": float, "dffits": float}, ...},
  "permutation_p_value": float,
  "conformal_intervals": {"<policy>": {"predicted": float, "lower": float, "upper": float}, ...},
  "aggregate_pearson_r": float
}
```

- `mmrv_scores`: per-policy aggregate sim score — best variant per task, averaged across tasks
- `real_mean_scores`: per-policy mean real-world success rate across tasks
- `task_correlations`: per-task Pearson correlation between best-variant sim and real scores across policies
- `fisher_z_mean_r`: combined per-task correlations with appropriate bias correction for averaging correlation coefficients
- `anova_eta_squared` / `anova_f_stats`: attribute variance of the pointwise sim-real gap (sim_{p,t,v} - real_{p,t}) to policy, task, and variant main effects; eta-squared as fraction of total SS; F-statistics using residual mean square
- `deming_calibration`: per-variant calibration regression of real on sim using all policy x task pairs, properly accounting for measurement noise in both variables — noise levels follow from trial counts in `experiment.db`
- `influence_diagnostics`: leverage, Cook's distance, and DFFITS for the linear model predicting real means from aggregate sim scores
- `permutation_p_value`: one-sided resampling-based significance test of the aggregate sim-real correlation (seed and iteration count from `experiment.db`)
- `conformal_intervals`: distribution-free prediction intervals from the aggregate sim-to-real model using a leave-one-out approach (confidence level from `experiment.db`); `predicted` is the full-model fitted value
- `aggregate_pearson_r`: Pearson correlation between `mmrv_scores` and `real_mean_scores`
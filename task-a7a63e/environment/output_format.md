# Output Specification

## JSON Output

Write results to `/app/results.json` with this structure:

```json
{
  "visual_matching": {
    "mmrv": 0.0,
    "pearson_r": 0.0,
    "pearson_p": 0.0,
    "kendall_tau_b": 0.0,
    "nrmse": 0.0,
    "bias": 0.0,
    "per_task_pearson": {
      "<task_name>": 0.0
    },
    "fisher_z_mean_r": 0.0,
    "pearson_r_ci_95": [0.0, 0.0]
  },
  "variant_aggregation": {
    "mmrv": 0.0,
    "pearson_r": 0.0,
    "pearson_p": 0.0,
    "kendall_tau_b": 0.0,
    "nrmse": 0.0,
    "bias": 0.0,
    "per_task_pearson": {
      "<task_name>": 0.0
    },
    "fisher_z_mean_r": 0.0,
    "pearson_r_ci_95": [0.0, 0.0]
  },
  "comparison": {
    "better_approach": "<approach with higher global Pearson r>",
    "mmrv_difference": 0.0,
    "pearson_difference": 0.0
  }
}
```

## Field Details

- All floating-point values: 4 decimal places, except `pearson_p` which uses 6 decimal places
- `per_task_pearson`: keys are task names exactly as stored in the database; values are floats or JSON `null` for undefined correlations
- `pearson_r_ci_95`: two-element list `[lower_bound, upper_bound]`
- `mmrv_difference`: visual_matching MMRV minus variant_aggregation MMRV
- `pearson_difference`: visual_matching Pearson r minus variant_aggregation Pearson r

## Scatter Plot

Generate `/app/plots/sim_vs_real.png` using gnuplot:
- X-axis: real-world success rates
- Y-axis: simulated success rates
- Plot both approaches as distinct point series with a legend
- Include a diagonal y=x reference line
- Label both axes

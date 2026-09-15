# Sim-to-Real Evaluation Metrics Specification

## Data Format

### CSV Files
- Lines starting with `#` are comments and must be ignored during parsing
- The first non-comment, non-empty line is the header row
- Column order varies between files; always use column headers to identify policies
- The `task` column contains the task name; all other columns are policy names with success rates
- Some entries may contain `NaN`, indicating missing measurements

### config.json
- `visual_matching.data_file`: path (relative to `data/`) for Visual Matching simulation results
- `variant_aggregation.variant_files`: list of paths (relative to `data/`) for variant simulation results
- `variant_aggregation.variant_weights`: quality weight for each variant file (sum to 1.0)
- `variant_aggregation.aggregation`: aggregation method (`"weighted_mean"`)
- `real_world_file`: path (relative to `data/`) for real-world reference results
- `output_file`: relative path for output JSON
- `bootstrap.seed`: integer seed for reproducible bootstrap procedures
- `bootstrap.n_iterations`: number of bootstrap iterations

## Variant Aggregation

For `weighted_mean` aggregation, compute the weighted average of success rates across variant files for each (task, policy) pair using the specified `variant_weights`. When a variant has `NaN` for a given (task, policy) pair, exclude that variant from the weighted average and renormalize the remaining weights to sum to 1.0 before computing the mean.

## Required Metrics

Compute the following for each evaluation approach (visual_matching and variant_aggregation):

### 1. MMRV (Mean Maximum Ranking Violation)

For each task with N policies:

Rank policies by **descending** success rate (rank 1 = highest value). For tied values, assign the average of the rank positions they span (e.g., two policies tied at positions 2 and 3 each receive rank 2.5).

Compute `sim_ranks` from simulation success rates and `real_ranks` from real-world success rates.

The Maximum Ranking Violation for task t is:

    MRV(t) = max { real_rank(i) − real_rank(j) }

over all ordered pairs (i, j) where `sim_rank(i) < sim_rank(j)` (i is ranked strictly higher in simulation) and `real_rank(i) > real_rank(j)` (i is ranked strictly lower in reality). If no such violating pairs exist, MRV(t) = 0.

MMRV = arithmetic mean of MRV(t) across all tasks. Lower values indicate better sim-to-real ranking consistency.

### 2. Pearson Correlation Coefficient

Pearson product-moment correlation coefficient `r` and two-tailed p-value, computed across all (task, policy) pairs. Flatten by iterating tasks in alphabetical order, and within each task iterate policies in alphabetical order.

### 3. Kendall's Tau-b

Kendall rank correlation with tie correction (tau-b variant), using the same flattened ordering as Pearson.

### 4. Per-Task Pearson Correlation

For each task individually, compute Pearson r across its policies (alphabetical policy order). If all simulation values for a task are identical (zero variance), the correlation is mathematically undefined: report `null` in the output JSON.

### 5. Fisher z-Transformed Mean Correlation

Compute a statistically appropriate average of per-task Pearson correlations using Fisher's z-transformation. Apply `arctanh` to each valid (non-null) per-task r value, compute the arithmetic mean in z-space, then apply `tanh` to obtain the mean correlation coefficient. Report as `fisher_z_mean_r`. Exclude null (undefined) per-task correlations from this computation.

### 6. NRMSE (Normalized Root Mean Square Error)

    NRMSE = RMSE / (max(real) − min(real))

where `RMSE = sqrt(mean((sim_i − real_i)²))` across all (task, policy) pairs. `max(real)` and `min(real)` are the global maximum and minimum real-world success rates across all pairs.

### 7. Bias

Mean signed difference across all (task, policy) pairs:

    Bias = mean(sim_i − real_i)

### 8. Bootstrap 95% Confidence Interval for Pearson r

Compute a percentile-based bootstrap 95% confidence interval for the global Pearson r.

Initialize a numpy random generator via `numpy.random.default_rng(seed)` using the seed from config.json. For each of `n_iterations` bootstrap iterations:

1. Draw N indices with replacement from {0, ..., N−1} using `rng.integers(0, N, size=N)`, where N is the total number of (task, policy) observations
2. Construct bootstrap samples by indexing into the flattened sim and real arrays
3. Compute Pearson r on the bootstrap sample; discard if undefined (zero-variance arrays)

Report the 2.5th and 97.5th percentiles (via `numpy.percentile`) of the valid bootstrap r values as `pearson_r_ci_95`.

## Output Format

Write a JSON file to `/app/results.json` with the following structure:

```json
{
  "visual_matching": {
    "mmrv": "<float, 4 decimal places>",
    "pearson_r": "<float, 4 decimal places>",
    "pearson_p": "<float, 6 decimal places>",
    "kendall_tau_b": "<float, 4 decimal places>",
    "nrmse": "<float, 4 decimal places>",
    "bias": "<float, 4 decimal places>",
    "per_task_pearson": {
      "<task_name>": "<float 4dp, or null if undefined>"
    },
    "fisher_z_mean_r": "<float, 4 decimal places>",
    "pearson_r_ci_95": ["<float, 4 dp lower>", "<float, 4 dp upper>"]
  },
  "variant_aggregation": {
    "...same fields as above..."
  },
  "comparison": {
    "better_approach": "<visual_matching or variant_aggregation, whichever has higher Pearson r>",
    "mmrv_difference": "<float, MMRV_vm minus MMRV_va, 4 decimal places>",
    "pearson_difference": "<float, Pearson_vm minus Pearson_va, 4 decimal places>"
  }
}
```

All floating-point values must be rounded to the specified number of decimal places. Task names in `per_task_pearson` must exactly match the task names from the data files. Use JSON `null` (not the string `"null"`) for undefined correlations.

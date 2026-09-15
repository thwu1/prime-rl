# Benchmark Evaluation Metrics Specification

## Overview

This document specifies the statistical metrics, data handling rules, and output
schema for the benchmark evaluation pipeline. The pipeline evaluates AI coding
agent models by analyzing results from multiple evaluation runs.

## Data Format

### Models (`models.json`)
JSON array of objects:
- `name`: Model identifier (string)
- `release_date`: Model release date in YYYY-MM-DD format (string)

### Tasks (`tasks.json`)
JSON array of objects:
- `id`: Task instance identifier (string)
- `created_at`: Task creation date in YYYY-MM-DD format (string)
- `repo`: Repository identifier (string)

### Run Results (`runs/{model_name}/run_{n}.jsonl`)
Each line is a JSON object with:
- `instance_id`: Task identifier (string, required)
- `resolved`: Boolean indicating success (optional; defaults to `false` if absent)
- `status`: One of `"completed"`, `"timeout"`, `"error"` (optional, informational)

### Missing Results
If a task does not appear in a run's JSONL file (e.g., due to environment setup
failure), it **must** be treated as a failure (`resolved=false`). The denominator
for all rate calculations is always the **total number of tasks being evaluated**,
not the number of tasks with entries in the run file.

## Metrics

### Resolved Rate
The mean of per-run resolved fractions:

    resolved_rate = (1/R) * sum(resolved_in_run_r / total_tasks, for r in 1..R)

where R is the number of runs and `total_tasks` is the number of tasks being
evaluated (after any time-window filtering).

### Standard Error of the Mean (SEM)
Using **sample** standard deviation with Bessel's correction (n-1 denominator):

    sample_variance = sum((rate_r - mean_rate)^2, for r in 1..R) / (R - 1)
    SEM = sqrt(sample_variance) / sqrt(R)

Note: the divisor for the variance is `R - 1`, NOT `R`.

### Pass@k (Unbiased Estimator)
For each task, given n total runs and c successful runs, compute:

    pass@k = 1 - C(n - c, k) / C(n, k)

where `C(a, b)` is the binomial coefficient ("a choose b").
When `a < b`, `C(a, b) = 0`, so `pass@k = 1.0` whenever `n - c < k`.

Report the **average** pass@k across all tasks.

This is the unbiased estimator from Chen et al. (2021), "Evaluating Large
Language Models Trained on Code". Do **NOT** use the biased/naive estimator
`1 - (1 - c/n)^k`, which systematically underestimates the true pass@k.

### Contamination Detection
A task is **potentially contaminated** for a model if the task's `created_at`
date is **strictly before** (`<`, not `<=`) the model's `release_date`.

Tasks created on the **same day** as the model's release are **not** considered
contaminated.

## Time-Window Filtering
The pipeline must support `--start-date` and `--end-date` CLI arguments.
When provided, only tasks with `created_at >= start_date` AND
`created_at <= end_date` should be included in the analysis. All metrics
(resolved rate, SEM, pass@k, contamination, task difficulty) are computed
only over the filtered task set.

## Output Schema

The output JSON must contain:

```json
{
  "time_window": {
    "start": "<YYYY-MM-DD or null>",
    "end": "<YYYY-MM-DD or null>"
  },
  "num_tasks": "<integer>",
  "num_runs_per_model": "<integer>",
  "rankings": [
    {
      "rank": "<integer, starting from 1>",
      "model": "<model name>",
      "resolved_rate": "<float>",
      "sem": "<float>",
      "pass_at_1": "<float>",
      "pass_at_3": "<float>",
      "pass_at_5": "<float>",
      "num_contaminated_tasks": "<integer>",
      "contamination_fraction": "<float>"
    }
  ],
  "task_difficulty": [
    {
      "task_id": "<string>",
      "mean_solve_rate": "<float>",
      "num_models_solved_at_least_once": "<integer>"
    }
  ]
}
```

- `rankings`: Sorted by `resolved_rate` **descending** (best model first).
- `task_difficulty`: Sorted by `mean_solve_rate` **ascending** (hardest first).
  - `mean_solve_rate`: Average of `c/n` across all models for a given task.
  - `num_models_solved_at_least_once`: Count of models with `c > 0`.

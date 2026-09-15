# Benchmark Evaluation Pipeline Specification

## Overview

This document specifies the evaluation methodology for a benchmark leaderboard
that assesses AI coding agents across multiple evaluation runs. The pipeline
ingests data from three heterogeneous sources, computes statistical metrics,
detects potential data contamination through both temporal and code-similarity
analysis, and produces a ranked leaderboard.

## Data Sources

### SQLite Database (`benchmark.db`)

The primary metadata store. Contains two tables:

**models**
- `name` TEXT PRIMARY KEY — model identifier
- `release_date` TEXT — YYYY-MM-DD format (date when training data pipeline was closed)
- `provider` TEXT — organization name
- `context_window` INTEGER — context window size in tokens

**tasks**
- `id` TEXT PRIMARY KEY — task instance identifier
- `created_at` TEXT — YYYY-MM-DD format (date the task was created/published)
- `repo` TEXT — repository identifier (owner/name)
- `language` TEXT — primary programming language

Use the database directly — no JSON metadata files exist.

### Run Result Files (`runs/{model_name}.parquet`)

Parquet files containing per-task evaluation results in wide format. Each model
has one Parquet file with columns:
- `instance_id` (VARCHAR) — matches `tasks.id`
- `r1` through `r5` (BOOLEAN, nullable) — resolved status for each of the 5 runs

A NULL value in a run column indicates a missing or error result (e.g., due to
environment setup failure or runtime error).

Each model has exactly 5 runs. Use DuckDB to read the Parquet files.

### Code Similarity Annotations (`similarity.csv`)

CSV with header row containing pairwise Jaccard similarity scores between
task patches:
- `task_a` — first task ID
- `task_b` — second task ID
- `jaccard_similarity` — float in [0, 1]

Relationships are symmetric: `(A, B, 0.85)` means both A↔B similarity is 0.85.
Each pair appears once. A task may appear in multiple pairs.

## Missing Results

If a run column is NULL for a task in the Parquet file, it **must** be treated
as a failure (`resolved = false`). The denominator for all rate calculations is
always the **total number of tasks being evaluated**, not the count of non-NULL
entries.

**Important**: When unpivoting Parquet columns from wide to long format using
DuckDB, be aware that DuckDB's `UNPIVOT` operation silently drops rows where
the unpivoted value is NULL by default. The pipeline must preserve NULL entries
so they can be coalesced to `false`.

## Metrics

### Resolved Rate

The mean of per-run resolved fractions:

    resolved_rate = (1/R) * SUM(resolved_in_run_r / T) for r in 1..R

where R is the number of runs (5) and T is the total task count (after any
time-window filtering).

### Standard Error of the Mean (SEM)

The SEM quantifies uncertainty in the resolved rate estimate from R runs.
The R=5 runs represent a finite random sample from the model's stochastic
evaluation process — they do not constitute the full population of possible
evaluation outcomes. The variance estimator must account for this
finite-sample context to avoid downward bias.

Reference: Bessel's correction adjusts for the bias in estimating population
variance from a finite sample.

    SEM = sqrt(variance_estimate / R)

### Pass@k

Estimate the probability that at least one of k independent runs solves a
task, averaged across all evaluated tasks. The estimator must produce
mathematically unbiased results for the benchmark's sample size (n=5 runs
per model per task).

Reference: Chen et al. (2021), "Evaluating Large Language Models Trained on
Code" — defines the appropriate unbiased estimator for pass@k evaluation
with finite samples.

Compute pass@1, pass@3, and pass@5.

## Contamination Detection

A task may be contaminated for a model through two mechanisms:

### Temporal Contamination

A task is temporally contaminated if it could have appeared in the model's
training data. The model's `release_date` represents the date the training
data pipeline was closed. Tasks that were created and publicly available
before this date could potentially have been included in training. A task
created on the same day as the release date was not yet available when the
pipeline was finalized and should **not** be flagged as contaminated.

### Code Similarity Contamination

A task is similarity-contaminated if it has Jaccard patch similarity >= 0.8
(from the similarity CSV) with any **temporally**-contaminated task. This
propagation is limited to one hop: only direct neighbors of
temporally-contaminated tasks inherit contamination status. Transitive
propagation — where a task similar to a merely-similarity-contaminated
(but not temporal) task is also flagged — must not occur, as it produces
false positives from coincidental code pattern chains.

### Combined Contamination Count

The `num_contaminated_tasks` for a model is the count of tasks in the
evaluated set that are either temporally contaminated or
similarity-contaminated (the union).

### Contamination Under Time-Window Filtering

Temporal contamination status is an intrinsic property of the model-task
pair, determined solely by comparing the task's creation date to the model's
training data cutoff. When the evaluation window is filtered by date range,
temporal determination uses the **full** (unfiltered) task set — a task's
temporal contamination status does not change based on the evaluation window.
The final contamination count includes only tasks present in the filtered
evaluation set.

## Time-Window Filtering

The CLI must support `--start-date` and `--end-date` arguments (YYYY-MM-DD).
When provided, only tasks with `created_at >= start_date` AND
`created_at <= end_date` are included in the evaluation. All metrics
(resolved rate, SEM, pass@k, contamination, task difficulty) are computed over
the filtered task set.

## CLI Interface

    python3 /app/src/pipeline.py [--data-dir DIR] [--output FILE] \
        [--start-date DATE] [--end-date DATE]

Defaults:
- `--data-dir`: `/app/data`
- `--output`: `/app/output/leaderboard.json`

## Output Schema

The output JSON must contain:

```json
{
  "time_window": {
    "start": "<YYYY-MM-DD or null>",
    "end": "<YYYY-MM-DD or null>"
  },
  "num_tasks": "<integer>",
  "num_runs_per_model": "<integer (always 5)>",
  "rankings": [
    {
      "rank": "<integer starting from 1>",
      "model": "<model name>",
      "resolved_rate": "<float rounded to 5 decimals>",
      "sem": "<float rounded to 5 decimals>",
      "pass_at_1": "<float rounded to 5 decimals>",
      "pass_at_3": "<float rounded to 5 decimals>",
      "pass_at_5": "<float rounded to 5 decimals>",
      "num_contaminated_tasks": "<integer>",
      "contamination_fraction": "<float rounded to 5 decimals>"
    }
  ],
  "task_difficulty": [
    {
      "task_id": "<string>",
      "mean_solve_rate": "<float rounded to 5 decimals>",
      "num_models_solved_at_least_once": "<integer>"
    }
  ]
}
```

- `rankings`: Sorted by `resolved_rate` **descending** (best model first).
  `contamination_fraction` = `num_contaminated_tasks / num_tasks`.
- `task_difficulty`: Sorted by `mean_solve_rate` **ascending** (hardest first).
  `mean_solve_rate` = average of `c/n` across all models for a given task.
  `num_models_solved_at_least_once` = count of models with `c > 0`.
- All float values rounded to 5 decimal places.

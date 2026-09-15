# Code Evaluation Pipeline Specification

## Database

SQLite database at `/app/benchmark.db` with three tables.

### problems

| Column | Type | Description |
|--------|------|-------------|
| task_id | TEXT PK | Unique problem identifier |
| prompt | TEXT | Execution preamble prepended before every candidate solution |
| test_code | TEXT | Test function `check(candidate)` source |
| entry_point | TEXT | Callable passed to `check` (e.g. `Solution().twoSum`) |
| difficulty | TEXT | Difficulty label |
| release_date | TEXT | `YYYY-MM-DD` publication date |
| tags | TEXT | Comma-separated topic tags |

### predictions

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| task_id | TEXT FK | References problems.task_id |
| model_name | TEXT | Model identifier |
| model_output | TEXT | Raw LLM response (may contain markdown fencing, prose, or multiple code blocks) |

### config

| Column | Type | Description |
|--------|------|-------------|
| key | TEXT PK | Parameter name |
| value | TEXT | Parameter value |

Keys: `temporal_cutoff` (ISO date string), `timeout_seconds` (execution timeout as string), `k_values` (comma-separated k parameters for pass@k).

## Code Extraction

Extract a single Python source from `model_output`. Outputs may be:
- Wrapped in ` ```python ... ``` ` or ` ``` ... ``` ` fences
- Bare code without any fences
- Multiple code blocks (select the longest syntactically valid one)

## Check Program Assembly

Concatenate these components in order to form an executable program:
1. `prompt` (from the problem row)
2. newline character
3. extracted code
4. newline character
5. `test_code` (from the problem row)
6. newline character
7. The string `check(<entry_point>)` where `<entry_point>` is the value from the problem row

Execute the assembled program in an isolated subprocess. A candidate **passes** if execution completes without raising any exception within `timeout_seconds`.

## Unbiased Pass@k Estimator

```
pass@k = 1 - C(n-c, k) / C(n, k)
```

Where n = number of predictions per (model, problem), c = number that pass all tests, k = evaluation parameter.

Product form for numerical stability:

```
C(n-c, k) / C(n, k) = product of (1 - k/i) for i from n-c+1 to n
```

Boundary: when `n - c < k`, `pass@k = 1.0`.

For each model, compute the mean of per-problem pass@k values across all evaluated problems.

## Temporal Decontamination

Only evaluate problems where `release_date >= temporal_cutoff` (the cutoff is read from the config table). Exclude all others from both evaluation and output.

## Output

Write `/app/output/leaderboard.json`:

```json
{
  "config": {
    "temporal_cutoff": "<string>",
    "timeout_seconds": <int>,
    "k_values": [<int>, ...]
  },
  "models": [
    {
      "rank": <int>,
      "model_name": "<string>",
      "num_problems": <int>,
      "pass@1": <float>,
      "pass@2": <float>,
      "pass@3": <float>,
      "per_problem": {
        "<task_id>": {"total": <int>, "correct": <int>},
        ...
      }
    }
  ]
}
```

Sort `models` by `pass@1` descending; assign 1-indexed ranks.

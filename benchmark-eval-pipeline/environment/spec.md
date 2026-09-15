# Benchmark Evaluation Pipeline Specification

## Overview

Implement the evaluation pipeline at `/app/evaluator.py`. The pipeline evaluates
candidate image edits against ground-truth renders across multiple camera views,
selects the best candidate per instance, and produces a statistical evaluation report.

## Allowed Dependencies

- `numpy` (numerical computation)
- `scipy.stats` (statistical functions)
- `PIL` / `Pillow` (image I/O and resizing)
- `tomllib` (configuration parsing)
- `sqlite3` (metric caching)
- Standard library modules

## Forbidden Dependencies (for structural similarity computation)

Do NOT use any of these for the structural image similarity metric:
`skimage`, `scikit-image`, `scipy.signal`, `scipy.ndimage`, `cv2` / `opencv`.

---

## Function Interface

### `photometric_loss(img1: ndarray, img2: ndarray) -> float`

Mean squared error between two images on normalized RGB pixel values.

- Input: numpy arrays of shape `(H, W, 3)` or `(H, W, 4)`, dtype `uint8` (0–255)
- RGBA input: use only the first 3 channels
- Mismatched dimensions: resize `img2` to match `img1` using bilinear interpolation
- Identical images → 0.0; maximally different (all-0 vs all-255) → 1.0

### `ssim_score(img1: ndarray, img2: ndarray, window_size: int = 11, K1: float = 0.01, K2: float = 0.03) -> float`

Structural similarity index between two images.

- Same input handling as `photometric_loss` (resize, normalize to `float64` in [0, 1])
- Dynamic range `L = 1.0`
- Compute per-channel, average across R, G, B
- Identical images must return exactly `1.0`
- Must be implemented from scratch (no forbidden imports above)

### `composite_distance(img1, img2, alpha=0.5, beta=0.5) -> float`

Weighted combination: `alpha * photometric_loss(img1, img2) + beta * (1 - ssim_score(img1, img2))`

### `multi_view_aggregate(per_view_scores: list[dict]) -> dict`

Average metrics across views, ignoring None entries.

- Input: list of dicts with keys `"pl"` and `"ssim"` (values: `float` or `None`)
- Output: dict with `"avg_pl"` and `"avg_ssim"`
- If all values for a metric are `None`, output `None` for that metric

### `swiss_tournament(candidates, target, n_rounds, metric_fn, seed=42) -> list[tuple]`

Swiss-system tournament for ranking candidates across multiple rounds.

- All candidates start at score `0.0`
- Each round: rank by score descending (ties broken by original index ascending)
- Pair candidates greedily from the top of the ranking; a candidate cannot face a previous opponent. If no valid partner remains, the candidate stays unpaired.
- Lowest-ranked unpaired candidate gets a bye (`+1` point; one bye per round)
- Each matched pair: evaluate `metric_fn(candidate, target)` for both; lower distance wins (`+1` point); equal → lower index wins
- After all rounds: tiebreak score = sum of final scores of all opponents faced
- Final sort: score descending, tiebreak descending, original index ascending
- Return: list of `(original_index, final_score, tiebreak_score)`
- Edge cases: 0 candidates → `[]`. 1 candidate → `[(0, 0.0, 0.0)]`

### `trimmed_mean(values: list[float], trim_fraction: float = 0.1) -> float`

Trimmed (truncated) arithmetic mean.

- Sort values. Let `k = floor(n × trim_fraction)`. Remove `k` from each end.
- Return mean of remaining. Empty list → `0.0`. If `2k ≥ n`, return full mean.

### `bca_bootstrap_ci(values, confidence=0.95, n_bootstrap=10000, seed=42) -> (float, float)`

Bias-corrected and accelerated bootstrap confidence interval for the mean.

- Empty → `(0.0, 0.0)`. Single value `v` → `(v, v)`
- Use `numpy.random.RandomState(seed)` for reproducibility
- Return `(lower_bound, upper_bound)`

### `load_config(path: str) -> dict`

Load evaluation parameters from a TOML configuration file. The config file uses
sections `[metrics]`, `[aggregation]`, and `[bootstrap]` with keys matching the
pipeline parameters (`alpha`, `beta`, `trim_fraction`, `confidence`, `n_bootstrap`, `seed`).

### `init_cache(db_path: str = "/app/cache.db") -> Connection`

Initialize a SQLite database for caching metric results. Create a `metric_cache`
table with columns: `goal_path TEXT`, `candidate_path TEXT`, `photometric_loss REAL`,
`ssim_score REAL`, with a composite primary key on `(goal_path, candidate_path)`.
Return the database connection.

### `evaluate_benchmark(data_dir: str, config: dict | None = None, cache_db: str | None = None) -> dict`

Full pipeline processing a benchmark directory tree.

**Directory structure**:
```
data_dir/
  <task_name>/
    <instance_name>/
      goal/
        view1.png, view2.png, ...
      candidate_0/
        view1.png, view2.png, ...
      candidate_1/
        ...
```

**Processing**: For each task/instance/candidate, compute per-view metrics against
the goal, aggregate across views, compute composite distance using config weights
(default `alpha=0.5`, `beta=0.5`). Select best candidate per instance (lowest
composite distance). Per-task score = trimmed mean of best distances. Per-task
CI via bootstrap. Overall score = harmonic mean of per-task scores. Overall CI =
bootstrap of all instance best-distances pooled across tasks.

If `config` is `None`, use default parameter values. If `cache_db` is provided,
cache per-image-pair metric computations in the SQLite database.

**Return format**:
```json
{
  "tasks": {
    "<task_name>": {
      "instances": {
        "<instance_name>": {
          "best_candidate": "<int>",
          "best_composite_distance": "<float>",
          "per_candidate": {
            "<cand_idx_str>": {
              "avg_pl": "<float or null>",
              "avg_ssim": "<float or null>",
              "composite": "<float>"
            }
          }
        }
      },
      "trimmed_mean_distance": "<float>",
      "ci_lower": "<float>",
      "ci_upper": "<float>"
    }
  },
  "overall": {
    "harmonic_mean_distance": "<float>",
    "ci_lower": "<float>",
    "ci_upper": "<float>"
  }
}
```

---

## CLI Interface

When invoked as:
```
python3 /app/evaluator.py --data-dir <dir> --output <file> [--config <path>] [--cache-db <path>]
```

- `--data-dir`: path to benchmark data directory (required)
- `--output`: path to write JSON evaluation report (required)
- `--config`: path to TOML config file (default: `/app/config.toml`)
- `--cache-db`: path to SQLite cache database (optional)

The CLI loads configuration, runs `evaluate_benchmark`, and writes the JSON result.

A financial ML dataset is stored in a DuckDB database at `/app/data/market.duckdb` with three tables:

- `features` — 5000 time-indexed observations, 20 numeric columns (`F_00`–`F_19`)
- `labels` — binary targets (`bin`) with a `t1` column indicating when each label's outcome resolves (1–10 business days ahead, creating temporal overlap between observations)
- `prices` — daily closing prices (`close`)

Schema details: `/app/data/metadata.json`.

Of the 20 features, 5 carry genuine predictive signal, 5 are linear combinations of those (redundant), and 10 are pure noise. Classify each feature correctly.

The temporal overlap between labels creates two biases that naive approaches fail to handle:

**Sampling bias.** Observations in densely overlapping regions are over-represented in uniform random samples. Your sampling scheme must produce draws with demonstrably higher average temporal independence than naive random sampling. Demonstrate this on a tractable subset (~100 labels, ~20 draws — the correct approach is O(n²) per draw).

**Evaluation bias.** Standard k-fold cross-validation leaks future information when training observations have outcomes that resolve during the test period. Your evaluation framework must prevent this leakage and report how many observations were excluded per fold.

Compute per-observation weights using return attribution from the price series, accounting for the number of concurrent labels sharing the same bars. Normalize weights to mean 1.

Assess feature importance using at least two independent methods and classify by consensus.

**Required output — `/app/results/results.json`:**

```json
{
  "sampling_analysis": {
    "avg_uniqueness_corrected": <float>,
    "avg_uniqueness_random": <float>
  },
  "sample_weights": {
    "mean_uniqueness": <float>,
    "mean_weight": <float>,
    "std_weight": <float>,
    "n_samples": <int>
  },
  "evaluation": {
    "mean_score": <float>,
    "std_score": <float>,
    "scores": [<float>, ...],
    "n_splits": <int>,
    "pct_embargo": <float>,
    "n_excluded_per_fold": [<int>, ...]
  },
  "feature_importance": {
    "rankings": {
      "<method_name>": ["F_xx", ...sorted by importance descending],
      ...
    }
  },
  "feature_classification": {
    "F_00": "informative"|"redundant"|"noise",
    ...
  }
}
```

**Required output — `/app/results/analysis.db` (SQLite):**

| Table | Columns |
|-------|---------|
| `sample_weights` | `date TEXT, weight REAL, uniqueness REAL` |
| `cv_assignments` | `fold INTEGER, date TEXT, role TEXT` where role ∈ {train, test, excluded} |
| `feature_scores` | `feature TEXT, method TEXT, score REAL` |

Do not use mlfinlab, hudson-thames, or equivalent pre-built financial ML libraries.
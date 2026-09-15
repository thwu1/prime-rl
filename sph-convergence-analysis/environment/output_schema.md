# Output Schema

Write `/app/results.json` with the following structure. All resolutions and quantities present in the dataset must be represented.

```json
{
  "similarity_analysis": {
    "<resolution>": {
      "<quantity>": {
        "run_<i>": {
          "distance": "<float>",
          "within_threshold": "<bool>"
        }
      }
    }
  },
  "outlier_detection": {
    "<resolution>": {
      "<quantity>": {
        "run_<i>": {
          "outlier_score": "<float>",
          "is_outlier": "<bool>"
        }
      }
    }
  },
  "ensemble_convergence": {
    "<resolution>": {
      "<quantity>": {
        "temporal_mean_of_ensemble_mean": "<float>",
        "temporal_mean_of_ensemble_variance": "<float>",
        "mean_converged": "<bool>",
        "variance_converged": "<bool>"
      }
    }
  },
  "spatial_convergence": {
    "<quantity>": {
      "convergence_order": "<float>",
      "extrapolated_value": "<float>",
      "values_used": {
        "fine": "<float>",
        "medium": "<float>",
        "coarse": "<float>"
      }
    }
  },
  "overall_assessment": {
    "all_similarity_pass": "<bool>",
    "all_converged": "<bool>",
    "expected_convergence_order": "<float>",
    "outlier_runs": ["<resolution>/<quantity>/run_<i>", "..."]
  }
}
```

## Field Descriptions

### similarity_analysis

For each run in each (resolution, quantity) group, compare the run's time series against the resolution's reference baseline. `distance` is the normalized time-series distance. `within_threshold` is `true` when `distance < distance_threshold` (from config).

### outlier_detection

Applied independently per (resolution, quantity) group. Compute a robust deviation score from the distribution of distances within each group. `is_outlier` is `true` when `|outlier_score| > outlier_score_threshold` (from config).

### ensemble_convergence

Ensemble statistics computed over non-outlier runs only. `temporal_mean_of_ensemble_mean` and `temporal_mean_of_ensemble_variance` are time-averaged values across all snapshots. `mean_converged` and `variance_converged` indicate whether the ensemble mean tracks the reference and the ensemble spread is acceptably small, evaluated against `convergence_threshold_mean` and `convergence_threshold_variance` from config.

### spatial_convergence

Estimated from ensemble means at the final snapshot across all resolutions. `convergence_order` is the observed order of spatial convergence. `extrapolated_value` is the estimated grid-independent value. `values_used` records the ensemble mean at the final snapshot for each resolution.

### overall_assessment

- `all_similarity_pass`: every run across all resolutions and quantities is within the distance threshold.
- `all_converged`: all (resolution, quantity) combinations pass both mean and variance convergence criteria.
- `expected_convergence_order`: mean convergence order across all quantities (excluding any NaN values).
- `outlier_runs`: list of identified outlier runs as `"<resolution>/<quantity>/run_<i>"` strings, sorted.

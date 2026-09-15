A pharmaceutical research team has binding affinity measurements for a set of training molecules and an uncharacterized screening library of candidate compounds. Produce a comprehensive virtual screening report that identifies diverse, drug-like candidates with predicted high binding affinity from the screening library.

Examine `/app/data/training_set.csv` and `/app/data/screening_library.csv` to understand their structure and quality. RDKit is available in the environment.

Create `/app/pipeline.py` that writes `/app/output/report.json` when executed via `python3 /app/pipeline.py`. The report must conform to this schema (all floats rounded to 4 decimal places):

```json
{
  "validation": {
    "training_total": 0,
    "training_valid": 0,
    "library_total": 0,
    "library_valid": 0,
    "library_unique": 0
  },
  "cascade_filter": {
    "input": 0,
    "after_lipinski": 0,
    "after_veber": 0,
    "after_pains": 0,
    "after_brenk": 0
  },
  "qsar_model": {
    "n_train": 0,
    "n_test": 0,
    "r2_test": 0.0,
    "rmse_test": 0.0
  },
  "applicability_domain": {
    "ad_threshold": 0.0,
    "n_in_ad": 0,
    "n_out_ad": 0
  },
  "clustering": {
    "n_clusters": 0,
    "cluster_sizes": []
  },
  "selected_candidates": [
    {
      "smiles": "",
      "predicted_pIC50": 0.0,
      "qed": 0.0,
      "composite_score": 0.0,
      "cluster_id": 0,
      "in_ad": true
    }
  ]
}
```

`selected_candidates` contains one representative per cluster (highest predicted affinity), restricted to molecules within the model's applicability domain. `composite_score` is `0.6 * normalized_pIC50 + 0.4 * QED`, where `normalized_pIC50` is min-max normalized across selected candidates (use 1.0 when all predictions are equal). Use canonical SMILES throughout.
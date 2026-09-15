A draft tool at `/app/analyze_draft.py` compares ML model performance across tabular datasets using benchmark result files at `/app/data/results/`. The draft contains multiple issues and missing functionality. Create a correct implementation at `/app/analyze.py`.

**CLI:**
```
python3 /app/analyze.py --results-dir <dir> --output <path> --metric <name> --alpha <float>
```

**Input:** The results directory contains JSON files. Valid model results have:
```json
{
  "model": "<name>",
  "results": [
    {"dataset": "<name>", "target_type": "binary", "n_folds": 5,
     "fold_metrics": {"<metric>": [<float|null>, ...]}}
  ]
}
```
The directory may contain non-model JSON files that must be skipped gracefully.

**Output:** Write JSON to `--output`:
```json
{
  "metric": "<name>", "direction": "maximize|minimize", "alpha": <float>,
  "n_models": <int>, "n_datasets": <int>,
  "model_dataset_means": {"<model>": {"<dataset>": <float>}},
  "average_ranks": {"<model>": <float>},
  "friedman_chi2": <float>, "friedman_p_value": <float>,
  "iman_davenport_f": <float>, "iman_davenport_p_value": <float>,
  "nemenyi_cd": <float>,
  "significant_pairs": [["<m1>", "<m2>"]],
  "cliques": [["<model>", ...]],
  "pairwise_wilcoxon": {
    "<m1>-<m2>": {"statistic": <float>, "p_value": <float>,
                  "p_corrected": <float>, "significant": <bool>}}
}
```

**Constraints:**
- AUC, Accuracy, F1, R2 maximize; Log Loss, MSE minimize.
- Null fold values excluded from means. Pairs with no valid folds excluded entirely.
- Compare on the dataset intersection across all models.
- Tied scores on a dataset must receive equal ranks.
- `significant_pairs`: pairs with rank difference > `nemenyi_cd`, each pair alphabetically sorted, list lexicographically sorted.
- `cliques`: maximal subsets with no pairwise rank difference > `nemenyi_cd`. Each clique sorted by ascending rank; cliques ordered by best rank.
- Wilcoxon keys: "ModelA-ModelB" (alphabetical). `p_corrected` must be non-decreasing when ordered by ascending raw p-value. `significant` is `p_corrected < alpha`.

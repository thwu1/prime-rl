Implement a type annotation similarity metric for Python type trees whose behavior is defined only through calibration examples — no specification of the underlying algorithm is provided.

The reference at `/app/reference.md` describes the type tree format, input data, output schema, and calibration examples. All data files are in `/app/data/`.

## Output

Write `/app/output/results.json` with the following exact structure:

```json
{
  "pair_scores": {
    "pair_01": <float>, "pair_02": <float>, ..., "pair_12": <float>
  },
  "type_meta": {
    "meta_01": {"depth": <int>, "count": <int>},
    ...
    "meta_06": {"depth": <int>, "count": <int>}
  },
  "repo_evaluation": {
    "overall_score": <float>,
    "overall_score_without_missing": <float>,
    "missing_count": <int>,
    "total_count": <int>,
    "scores_by_depth": {"1": <float>, "2": <float>, "3": <float>},
    "consistency_score_gt": <float>,
    "consistency_score_pred": <float>
  }
}
```

### `pair_scores`

Compute a similarity score for each of the 12 type pairs in `/app/data/type_pairs.json`. Keys are `pair_01` through `pair_12`. Every score must be a float in the range [0.0, 1.0].

### `type_meta`

Compute structural metadata for each of the 6 types in `/app/data/meta_types.json`. Keys are `meta_01` through `meta_06`. Each entry has:
- `depth`: maximum nesting level of the type tree (a leaf type has depth 1); must be an integer >= 1.
- `count`: total number of nodes in the type tree; must be an integer >= 1.

### `repo_evaluation`

Evaluate predicted types against ground truth using the same similarity metric as pair scoring, with the following required fields:
- `total_count` (int): number of variables evaluated.
- `missing_count` (int): number of ground truth variables absent from predictions.
- `overall_score` (float): mean similarity across all evaluated variables (missing variables score 0.0).
- `overall_score_without_missing` (float): mean similarity excluding missing variables.
- `scores_by_depth` (object): per-depth-group average scores with **string** keys (e.g. `"1"`, `"2"`, `"3"`), grouping variables by their ground truth type depth.
- `consistency_score_gt` (float): type-checking consistency derived from the ground truth `filtered_error_count`.
- `consistency_score_pred` (float): type-checking consistency derived from the predicted `filtered_error_count`.

## Validation

All calibration values listed in `/app/reference.md` must be reproduced within **1e-6** absolute tolerance. The implementation must also generalize correctly to the remaining (non-calibrated) inputs — 5 blind pair scores, 3 blind type metadata entries, and the full repo evaluation.
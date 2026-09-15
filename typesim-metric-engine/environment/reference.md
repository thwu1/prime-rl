# Type Annotation Similarity — Reference

## Type Tree Format

Types are represented as JSON objects:

- **Instance type**: `{"kind": "Instance", "origin": "<type_name>", "args": [<type>, ...]}`
  Concrete types like `int`, `str`, `list`, `dict`. The `args` field contains generic type parameters (empty for non-generic types).

- **Any type**: `{"kind": "Any"}`
  Python's `typing.Any`.

- **None type**: `{"kind": "None"}`
  `None` / `NoneType`.

- **Union type**: `{"kind": "Union", "items": [<type>, ...]}`
  `Union[X, Y, ...]` or `Optional[X]` (= `Union[X, None]`).

- **Tuple type**: `{"kind": "Tuple", "items": [<type>, ...]}`
  `Tuple[X, Y, ...]` with fixed element types.

## Input Data Files

- `/app/data/attribute_registry.json` — Contains `base_attributes` (attributes common to all Python objects) and `types` (mapping each type origin name to its full attribute list).

- `/app/data/type_pairs.json` — Array of `{id, type_a, type_b}` objects. Produce a similarity score for each pair.

- `/app/data/meta_types.json` — Array of `{id, type}` objects. Produce structural metadata for each type.

- `/app/data/repo_ground_truth.json` — Ground truth type annotations: `filtered_error_count` (integer) and `types` (variable name → type tree).

- `/app/data/repo_predicted.json` — ML-predicted type annotations: `filtered_error_count` (integer) and `types` (variable name → type tree).

- `/app/data/repo_baseline.json` — Pre-prediction baseline: `types` (variable name → type tree).

## Required Output

Write to `/app/output/results.json`:

```json
{
  "pair_scores": {"pair_01": <float>, ...},
  "type_meta": {"meta_01": {"depth": <int>, "count": <int>}, ...},
  "repo_evaluation": {
    "overall_score": <float>,
    "overall_score_without_missing": <float>,
    "missing_count": <int>,
    "total_count": <int>,
    "scores_by_depth": {"1": <float>, ...},
    "consistency_score_gt": <float>,
    "consistency_score_pred": <float>
  }
}
```

- `pair_scores`: similarity score for each type pair (values in [0.0, 1.0]).
- `type_meta`: structural depth (maximum nesting level of the type tree, where a leaf type has depth 1) and node count (total number of nodes in the type tree) for each type.
- `repo_evaluation`: per-variable comparison of ground truth vs predicted types using the same similarity metric as pair scoring. Variables absent from predictions score 0.0. `scores_by_depth` groups results by ground truth type depth (string keys). `consistency_score_gt` and `consistency_score_pred` are derived from the respective `filtered_error_count` values.

## Calibration Data

Your implementation must reproduce every calibration value within 1e-6 tolerance and generalize correctly to all inputs beyond this set.

### Pair Similarity

| ID | Type A | Type B | Score |
|----|--------|--------|-------|
| pair_01 | `int` | `int` | 1.000000 |
| pair_02 | `int` | `float` | 0.812500 |
| pair_03 | `int` | `str` | 0.068966 |
| pair_04 | `List[int]` | `List[float]` | 0.906250 |
| pair_06 | `Union[str, None]` | `str` | 0.500000 |
| pair_07 | `Union[int, str]` | `Union[str, int]` | 1.000000 |
| pair_11 | `int` | `List[int]` | 0.030303 |

### Type Metadata

| ID | Type | Depth | Count |
|----|------|-------|-------|
| meta_01 | `int` | 1 | 1 |
| meta_02 | `List[int]` | 2 | 2 |
| meta_04 | `Union[str, None]` | 2 | 3 |

### Repository Evaluation

| Metric | Value |
|--------|-------|
| total_count | 20 |
| missing_count | 1 |
| consistency_score_gt | 0.223130 |
| consistency_score_pred | 0.018316 |

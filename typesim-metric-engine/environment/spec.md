# TypeSim: Type Similarity Metric Specification

This document specifies the TypeSim algorithm for computing structural similarity
between Python type annotations. Implement the complete evaluation pipeline as
described below.

## 1. Type Tree Format

Types are represented as JSON objects with the following schemas:

- **Instance type**: `{"kind": "Instance", "origin": "<type_name>", "args": [<type>, ...]}`
  Represents concrete types like `int`, `str`, `list`, `dict`, etc.
  The `args` field contains generic type parameters (empty for non-generic types).

- **Any type**: `{"kind": "Any"}`
  Represents Python's `typing.Any`.

- **None type**: `{"kind": "None"}`
  Represents `None` / `NoneType`.

- **Union type**: `{"kind": "Union", "items": [<type>, ...]}`
  Represents `Union[X, Y, ...]` or `Optional[X]` (which is `Union[X, None]`).

- **Tuple type**: `{"kind": "Tuple", "items": [<type>, ...]}`
  Represents `Tuple[X, Y, ...]` with fixed element types.

## 2. String Representation

Compute a canonical string representation for each type tree:

```
str_repr(t):
  if t.kind == "Instance":
    if t.args is empty: return t.origin
    else: return t.origin + "[" + join(str_repr(a) for a in t.args, ", ") + "]"
  if t.kind == "Any": return "Any"
  if t.kind == "None": return "None"
  if t.kind == "Union": return "Union[" + join(str_repr(i) for i in t.items, ", ") + "]"
  if t.kind == "Tuple": return "tuple[" + join(str_repr(i) for i in t.items, ", ") + "]"
```

Examples: `"int"`, `"list[int]"`, `"dict[str, int]"`, `"Union[str, None]"`, `"tuple[int, str]"`.

## 3. Type Analysis (analyze_type)

Extract the name, origin key, and type arguments from a type tree:

```
analyze_type(t):
  if t.kind == "Instance": return (t.origin, t.origin, t.args)
  if t.kind == "Any":      return ("Any", "Any", [])
  if t.kind == "None":     return ("None", "None", [])
  if t.kind == "Tuple":    return ("tuple", "tuple", t.items)
```

**Note**: Union types are NOT processed by analyze_type. They are handled
separately (see Section 7). If a type kind is not recognized (not Instance,
Any, None, Union, or Tuple), it should be treated as unsupported and skipped.

## 4. Type Metadata (get_type_meta)

Compute recursive depth and node count for a type tree:

```
get_type_meta(t) -> (depth, count):
  meta_depth = 1
  meta_count = 0

  if t.kind == "Union":
    for item in t.items:
      child_depth, child_count = get_type_meta(item)
      meta_depth = max(meta_depth, child_depth + 1)
      meta_count += child_count
  else:
    name, origin, type_args = analyze_type(t)
    for arg in type_args:
      child_depth, child_count = get_type_meta(arg)
      meta_depth = max(meta_depth, child_depth + 1)
      meta_count += child_count

  meta_count += 1
  return (meta_depth, meta_count)
```

## 5. Attribute Lookup (get_type_attributes)

Load the attribute registry from `/app/data/attribute_registry.json`. It contains:
- `base_attributes`: list of base-level attributes common to all objects
- `types`: mapping from origin name to its attribute list

```
get_type_attributes(origin_key) -> set of strings:
  return set(registry.types[origin_key])
```

For the denominator adjustment in similarity computation, use:
```
get_base_attributes() -> set of strings:
  return set(registry.base_attributes)
```

## 6. Origin Similarity (_get_type_info_similarity)

Compute structural similarity between two type origins based on their attribute sets:

```
_get_type_info_similarity(a_origin, b_origin) -> float:
  a_attrs = get_type_attributes(a_origin)
  b_attrs = get_type_attributes(b_origin)
  base = get_base_attributes()

  a_minus_b = a_attrs - b_attrs    # attributes unique to a
  b_minus_a = b_attrs - a_attrs    # attributes unique to b
  common = a_attrs & b_attrs       # shared attributes

  numerator = |a_minus_b| + |b_minus_a|
  denominator = |common - base| + |a_minus_b| + |b_minus_a|

  if denominator == 0 and numerator == 0:
    return 1.0
  return 1.0 - numerator / denominator
```

This is a Jaccard-like measure that excludes base-level attributes from the
denominator, focusing similarity on the meaningful, type-specific attributes.

## 7. Within-Level Comparison (compare_within_level)

Compare two lists of types, either positionally or via optimal matching:

```
compare_within_level(a_list, b_list, is_union) -> float:
  if is_union:
    # Build cost matrix and find optimal assignment (Hungarian algorithm)
    # Matrix dimensions: rows = len(b_list), cols = len(a_list)
    cost_matrix[i][j] = get_type_similarity(b_list[i], a_list[j])
      for all i in 0..len(b_list)-1, j in 0..len(a_list)-1

    # Find assignment that MAXIMIZES total similarity
    # Use scipy.optimize.linear_sum_assignment on the negated matrix
    row_ind, col_ind = linear_sum_assignment(-cost_matrix)
    score = sum(cost_matrix[row_ind[k]][col_ind[k]] for k in range(len(row_ind)))
  else:
    # Positional comparison (for generic type arguments)
    score = 0
    for i in 0..min(len(a_list), len(b_list))-1:
      score += get_type_similarity(a_list[i], b_list[i])

  score /= max(len(a_list), len(b_list))
  return score
```

## 8. Type Similarity (get_type_similarity)

The main recursive similarity function:

```
get_type_similarity(a_type, b_type) -> float:
  # Case 1: a is Union, b is not Union
  if a_type.kind == "Union" and b_type.kind != "Union":
    return compare_within_level(a_type.items, [b_type], is_union=True)

  # Case 2: a is not Union, b is Union
  if a_type.kind != "Union" and b_type.kind == "Union":
    return compare_within_level([a_type], b_type.items, is_union=True)

  # Case 3: both are Union
  if a_type.kind == "Union" and b_type.kind == "Union":
    return compare_within_level(a_type.items, b_type.items, is_union=True)

  # Case 4: neither is Union
  a_name, a_origin, a_args = analyze_type(a_type)
  b_name, b_origin, b_args = analyze_type(b_type)

  # Short-circuit: identical string representations
  if str_repr(a_type) == str_repr(b_type):
    score = 1.0
  else:
    score = _get_type_info_similarity(a_origin, b_origin)

  # Recurse into type arguments
  if a_args and b_args:
    # Both have arguments: average origin score with argument score
    score = (score + compare_within_level(a_args, b_args, is_union=False)) / 2
  elif a_args or b_args:
    # Only one side has arguments: penalize by halving
    score = score / 2

  return score
```

## 9. Repository-Level Evaluation (compare_type_info)

Given three type dictionaries (ground truth, predicted, baseline), compute
per-variable similarity scores:

```
compare_type_info(gt_types, pred_types, baseline_types) -> (score_dict, missing_vars, meta_dict):
  score_dict = {}
  missing_vars = set()
  meta_dict = {}

  for var_name in gt_types:
    gt_type = gt_types[var_name]

    # Skip if ground truth type is Any
    if gt_type.kind == "Any":
      continue

    # Skip if variable exists in baseline with non-Any type
    # (meaning it was already typed before ML prediction)
    if var_name in baseline_types and baseline_types[var_name].kind != "Any":
      continue

    meta_dict[var_name] = get_type_meta(gt_type)

    if var_name in pred_types:
      score_dict[var_name] = get_type_similarity(gt_type, pred_types[var_name])
    else:
      score_dict[var_name] = 0.0
      missing_vars.add(var_name)

  return (score_dict, missing_vars, meta_dict)
```

## 10. Consistency Score

Compute type-checking consistency from mypy error counts:

```
compute_consistency_score(num_errors, num_vars) -> float:
  return exp(-num_errors / num_vars * 10)
```

Where `exp` is the natural exponential function.

## 11. Aggregate Metrics

From the per-variable results, compute:

- **overall_score**: mean of all values in score_dict
- **overall_score_without_missing**: `overall_score * total_count / (total_count - missing_count)`
  (If all variables are missing, this is 0.)
- **scores_by_depth**: group variables by their `meta.depth` (capped at 5),
  compute mean score per depth level
- **consistency_score_gt**: `compute_consistency_score(gt_error_count, total_count)`
- **consistency_score_pred**: `compute_consistency_score(pred_error_count, total_count)`

Where `total_count = len(score_dict)` and `missing_count = len(missing_vars)`.

## 12. Required Output

Write results to `/app/output/results.json` with this structure:

```json
{
  "pair_scores": {
    "pair_01": <float>,
    ...
  },
  "type_meta": {
    "meta_01": {"depth": <int>, "count": <int>},
    ...
  },
  "repo_evaluation": {
    "overall_score": <float>,
    "overall_score_without_missing": <float>,
    "missing_count": <int>,
    "total_count": <int>,
    "scores_by_depth": {
      "1": <float>,
      "2": <float>,
      ...
    },
    "consistency_score_gt": <float>,
    "consistency_score_pred": <float>
  }
}
```

## 13. Input Data Files

- `/app/data/attribute_registry.json` — Type attribute definitions
- `/app/data/type_pairs.json` — Array of type pairs to score
- `/app/data/meta_types.json` — Array of types for metadata computation
- `/app/data/repo_ground_truth.json` — Ground truth types + `filtered_error_count`
- `/app/data/repo_predicted.json` — Predicted types + `filtered_error_count`
- `/app/data/repo_baseline.json` — Baseline (stripped) types

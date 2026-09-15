# PLE Behavioral Specification

## Bin Computation

`compute_bins(X, n_bins, *, y=None, regression=None, tree_kwargs=None)` returns
a list of 1-D float64 edge arrays, one per column of X.

### Quantile Mode (tree_kwargs is None)

Compute `n_bins + 1` equally-spaced quantile points from 0.0 to 1.0 per column,
then deduplicate. Both `y` and `regression` must be `None`.

### Tree Mode (tree_kwargs provided)

Fit a decision tree per column with `max_leaf_nodes = n_bins`:
- `DecisionTreeRegressor` when `regression is True`
- `DecisionTreeClassifier` when `regression is False`

Edge array = sorted unique union of {column minimum, tree split thresholds, column maximum}.

Both `y` and `regression` are required. `max_leaf_nodes` must not appear in
`tree_kwargs`. Providing `y` without `tree_kwargs` is invalid.

### Input Validation (all raise ValueError)

- Non-finite values in X
- Fewer than 2 rows
- Any constant column
- `n_bins <= 1` or `n_bins >= len(X)`

## Encoding

A feature with edge array of length `k + 1` produces `k` components.

### Component Formula

Component `j` (0-indexed, 0 <= j < k): `(x - edges[j]) / (edges[j+1] - edges[j])`

### Clamping Rules

| Condition            | Rule                          |
|----------------------|-------------------------------|
| k = 1 (single bin)  | No clamping                   |
| j = 0 (first)       | Upper-bounded at 1.0 only     |
| j = k-1 (last)      | Lower-bounded at 0.0 only     |
| Otherwise (interior) | Clamped to [0.0, 1.0]        |

### Structured Layout — shape (batch, n_features, max_n_bins)

For a feature with `k` bins where `max_n_bins = max(k_i)`:
- Components 0 through k-2 occupy positions 0 through k-2
- Component k-1 (the last) occupies position max_n_bins - 1
- Positions k-1 through max_n_bins - 2 are zero-padded

### Flat Layout — shape (batch, total_n_bins)

Per feature, extract from the structured output: positions [0, 1, ..., k-2, max_n_bins-1].
Concatenate across features in column order.

## CLI

`python3 /app/ple_encode.py --input P --n-bins N --format {structured,flat} --output P`

The `--format flat` option must produce flat-encoded output (not structured).

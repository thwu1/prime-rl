A DuckDB database at `/app/catalog.duckdb` contains four relational tables (R, S, T, U). Table and column statistics including equi-depth histograms are at `/opt/task_data/stats.json`, and a workload of eight join queries is at `/opt/task_data/queries.json`.

Implement `/app/optimizer.py` exposing a function `optimize(stats: dict, query: dict) -> dict` that returns the optimal join plan for each query. The output format specification is at `/opt/task_data/framework.py` and a calibration example with a complete expected plan tree is at `/opt/task_data/calibration.json`.

## Plan tree structure

The returned dict is a binary tree of plan nodes.

Leaf node (base table scan, after any filter application):

```json
{"table": "<name>", "estimated_rows": <float>, "total_cost": 0.0}
```

Join node:

```json
{"left": <plan>, "right": <plan>, "estimated_rows": <float>, "node_cost": <float>, "total_cost": <float>}
```

## Constraints

- The plan must include all tables from the query and form a valid binary tree with exactly `n-1` join nodes for `n` tables.
- Cost model is hash join: `node_cost` equals `left.estimated_rows + right.estimated_rows`.
- Cost consistency: `total_cost = node_cost + left.total_cost + right.total_cost`. Leaf nodes have `total_cost` of `0.0`.
- Filter predicates in the query must be applied to leaf nodes, reducing `estimated_rows` using histogram-based selectivity estimation from the column statistics.
- Plans must be optimal: the root `total_cost` must equal the minimum achievable cost across all valid join orderings for the query.
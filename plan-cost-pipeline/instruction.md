A cardinality estimation evaluation pipeline at `/app/analyze.sh` processes query workload data through a multi-tool chain (shell, jq, awk, python) and produces a cost analysis report. The pipeline is broken — it crashes and/or produces incorrect results. Fix all bugs so that `bash /app/analyze.sh` successfully processes query data from `/app/data/queries/*.json` and writes a correct report to `/app/results/report.json`.

The pipeline has four stages:

1. `/app/analyze.sh` (shell) orchestrates per-query evaluation by invoking `jq` with the filter `/app/lib/costs.jq` to compute subset graph edge costs and Q-Errors for each query
2. `/app/lib/planner.py` (python) finds optimal and estimated query plans via DP shortest path on the computed edge costs
3. `/app/lib/stats.awk` (awk) aggregates collected Q-Error values into statistics from a pipe-separated intermediate file
4. `/app/lib/report.py` (python) combines plan costs and statistics into the final JSON report

**Cost model "C" specification:** Each edge in the subset graph connects a superset (size N) to a subset (size N-1). The diff is the single newly-joined table. `node1` = subset (existing subplan), `node2` = diff (new table). For a Nested Loop Index Join (NILJ), the single-table side is probed via index at a factor of 0.001 times its cardinality, while the other side is fully scanned. When `node1` is the single table, NILJ cost = `card(node2) + 0.001 * card(node1)`. When `node2` is the single table, NILJ cost = `card(node1) + 0.001 * card(node2)`. Hash join cost = `card(node1) * card(node2)`. Edge cost = `min(NILJ, hash_join)`. Zero cardinalities must be clamped to 1 before use in any cost or Q-Error computation.

**Q-Error:** `max(actual/estimated, estimated/actual)`. Zero cardinalities must be clamped to 1 before division.

**Plan cost:** A SOURCE node connects to each single-table node with edge cost 1.0. The optimal plan is the minimum-cost path from the full-table node to SOURCE. Plan cost = sum of edge costs along the path, excluding the SOURCE edge. The estimated plan is found using estimated cardinalities for edge weights, but its reported cost must be the TRUE cost (using actual cardinalities) of that same path.

**Output** `/app/results/report.json`:
```json
{
  "qerror_stats": {"count": <int>, "mean": <float>, "median": <float>, "p90": <float>, "p95": <float>, "p99": <float>},
  "plan_costs": [{"name": "<str>", "opt_cost": <float>, "est_cost": <float>, "relative_cost": <float>}, ...],
  "total_opt_cost": <float>,
  "total_est_cost": <float>,
  "total_relative_cost": <float>
}
```

`total_relative_cost = total_est_cost / total_opt_cost`. Plan costs list must be sorted by query name. All Q-Error values from all subplans of all queries contribute to the aggregate statistics. Percentiles use linear interpolation.

"""
Framework for cost-based join order optimization.

This module provides data structures for table statistics, queries, and join plans.
The agent must implement optimizer.py with a function:

    optimize(stats: dict, query: dict) -> dict

See /app/queries.json for query format and /app/stats.json for statistics format.

"""

import json
from typing import Any


def load_stats(path: str = "/app/stats.json") -> dict:
    """Load table statistics from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_queries(path: str = "/app/queries.json") -> list:
    """Load queries from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return data["queries"]


# ============================================================
# COST MODEL SPECIFICATION
# ============================================================
#
# All formulas below are normative. An optimizer implementation
# MUST use exactly these formulas to produce correct results.
#
# 1. FILTER SELECTIVITY (histogram-based)
# ----------------------------------------
# Histograms use half-open intervals: bucket covers [lower, upper).
#
# For predicate "col >= val":
#   For each bucket [lo, hi) with count c:
#     if val <= lo:  contribution = c          (full bucket)
#     if val >= hi:  contribution = 0          (no overlap)
#     else:          contribution = c * (hi - val) / (hi - lo)
#   selectivity = sum(contributions) / table_row_count
#
# For predicate "col > val":  treat as col >= val (continuous approx.)
#
# For predicate "col <= val":
#   For each bucket [lo, hi) with count c:
#     if val >= hi:  contribution = c
#     if val <= lo:  contribution = 0
#     else:          contribution = c * (val - lo) / (hi - lo)
#   selectivity = sum(contributions) / table_row_count
#
# For predicate "col < val":  treat as col <= val (continuous approx.)
#
# For predicate "col = val":
#   selectivity = 1.0 / column_ndv
#
# Conjunction of predicates on the SAME table:
#   selectivity = product of individual selectivities  (independence)
#
# Filtered table cardinality:
#   filtered_rows = row_count * product(selectivities)
#
# 2. NDV PROPAGATION
# ------------------
# After filtering a table with selectivity s:
#   V_filtered(col) = min(NDV(col), ceil(filtered_rows))
#
# After joining results L and R on L.a = R.b:
#   Let result_card = estimated join cardinality.
#   For the join columns a and b:
#     V_result(a) = V_result(b) = min(V_L(a), V_R(b), ceil(result_card))
#   For any other column c from L:
#     V_result(c) = min(V_L(c), ceil(result_card))
#   For any other column c from R:
#     V_result(c) = min(V_R(c), ceil(result_card))
#
# 3. JOIN CARDINALITY
# -------------------
# For equi-join on L.a = R.b:
#   |L join R| = |L| * |R| / max(V(L.a), V(R.b))
#
# Cross products (no predicate connecting L and R subsets) are NOT
# permitted. The optimizer must only consider partitions where both
# subsets are connected by at least one join predicate.
#
# 4. HASH JOIN COST
# -----------------
# cost(left, right) = |left| + |right|
#
# Total plan cost = sum of all join-node costs in the tree.
# Leaf nodes (base table scans, possibly filtered) have cost 0.
#
# 5. DYNAMIC PROGRAMMING
# -----------------------
# Enumerate all subsets of the query's tables. For each subset of
# size > 1, consider all ways to partition it into two non-empty
# subsets (S1, S2) such that:
#   (a) S1 union S2 = S
#   (b) At least one join predicate connects a table in S1 to a
#       table in S2.
#
# For each valid partition, the cost is:
#   cost(S) = cost(S1) + cost(S2) + |result(S1)| + |result(S2)|
#
# Pick the partition with minimum cost(S).
# The optimal plan for the full set of tables is the answer.
#
# ============================================================
# OUTPUT FORMAT
# ============================================================
#
# The optimize() function must return a dict representing the
# join plan tree:
#
# Leaf node (base table, possibly filtered):
# {
#     "table": "R",
#     "estimated_rows": <float>,
#     "total_cost": 0.0
# }
#
# Internal node (join):
# {
#     "left": <plan node>,
#     "right": <plan node>,
#     "estimated_rows": <float>,  # output cardinality of this join
#     "node_cost": <float>,       # |left.estimated_rows| + |right.estimated_rows|
#     "total_cost": <float>       # node_cost + left.total_cost + right.total_cost
# }
#
# The root node's total_cost must equal the optimal (minimum) total
# cost over all valid join orderings.

"""
Join optimizer output specification.

Implement /app/optimizer.py with:

    optimize(stats: dict, query: dict) -> dict

Input data:
  /opt/task_data/stats.json       - table and column statistics
  /opt/task_data/queries.json     - join query workload
  /opt/task_data/calibration.json - worked example with expected plan

Exploration resource:
  /app/catalog.duckdb - DuckDB database with actual table data

"""

import json


def load_stats(path="/opt/task_data/stats.json"):
    """Load table statistics from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_queries(path="/opt/task_data/queries.json"):
    """Load queries from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return data["queries"]


# ============================================================
# OUTPUT FORMAT
# ============================================================
#
# optimize() returns a dict representing a binary join plan tree.
#
# Leaf node (base table scan, possibly after filter application):
# {
#     "table": "<table_name>",
#     "estimated_rows": <float>,   # rows after any filter predicates
#     "total_cost": 0.0
# }
#
# Join node:
# {
#     "left": <plan_node>,
#     "right": <plan_node>,
#     "estimated_rows": <float>,   # estimated output cardinality
#     "node_cost": <float>,        # cost of this individual join
#     "total_cost": <float>        # node_cost + left.total_cost + right.total_cost
# }
#
# The root's total_cost is the sum of all node_cost values in the
# tree and must equal the minimum achievable cost across all valid
# join orderings for the query.

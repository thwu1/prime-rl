"""
Query Optimizer Entry Point.

Reads catalog statistics from /data/catalog.db (SQLite) and query definitions
from /data/queries.json. For each query, produces an optimal physical execution
plan and writes results to /app/output/.

Required outputs per query:
  /app/output/{query_id}_plan.json  — optimal plan as JSON
  /app/output/{query_id}_plan.dot   — plan tree in graphviz DOT format
  /app/output/{query_id}_plan.png   — rendered plan visualization

JSON plan format:
{
  "query_id": "<id>",
  "total_cost": <float>,           // sum of est_cost across all tree nodes
  "plan": <plan_node>
}

where <plan_node> is:
{
  "op": "HashJoin" | "SortMergeJoin" | "SeqScan" | "IndexScan" | "Filter",
  "table": "<name>",               // SeqScan and IndexScan only
  "join_cond": "<left>=<right>",    // join operators only
  "filter_cond": "<col><op><val>",  // Filter and IndexScan only
  "est_card": <int>,                // estimated output cardinality
  "est_cost": <float>,              // THIS node's operator cost (not cumulative)
  "tables": ["<t1>", ...],          // all base tables in this subtree
  "children": [<plan_node>, ...]    // child nodes (if any)
}

For HashJoin:  children[0] = probe side (larger), children[1] = build side.
For Filter:    children[0] = child scan.
For SeqScan/IndexScan: no children.
For SortMergeJoin: children[0] = left, children[1] = right.

The optimizer must:
- Read all statistics and cost parameters from /data/catalog.db via SQL.
- Apply filter pushdown (filters adjacent to base table scans, below joins).
- Consider both HashJoin and SortMergeJoin, choosing the cheaper operator.
- Consider IndexScan when a B-tree index exists and selectivity is low enough.
- Understand that scan type affects sort order, which affects join operator cost.
- Use the cost formulas from /data/cost_model.py with parameters from catalog.db.
- Generate graphviz DOT and render PNG via the dot command.

"""

import json
import os
import sqlite3


def optimize_query(query: dict, catalog_conn: sqlite3.Connection) -> dict:
    """
    Given a query specification and catalog connection, return the optimal
    execution plan as a nested dictionary.

    TODO: Implement this function.
    """
    raise NotImplementedError("Implement the multi-operator query optimizer")


def main():
    conn = sqlite3.connect('/data/catalog.db')
    conn.row_factory = sqlite3.Row

    with open('/data/queries.json') as f:
        queries = json.load(f)

    os.makedirs('/app/output', exist_ok=True)

    for query in queries:
        plan = optimize_query(query, conn)
        output_path = f'/app/output/{query["id"]}_plan.json'
        with open(output_path, 'w') as f:
            json.dump(plan, f, indent=2)
        print(f'Query {query["id"]}: total_cost={plan["total_cost"]:.3f}')

    conn.close()


if __name__ == '__main__':
    main()

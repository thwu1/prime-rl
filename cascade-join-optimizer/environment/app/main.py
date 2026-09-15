"""
Query Optimizer Entry Point.

Reads the table catalog from /app/catalog.json and query specifications from
/app/queries.json. For each query, produces an optimal physical execution plan
and writes it to /app/output/{query_id}_plan.json.

Expected output JSON format for each plan file:
{
  "query_id": "<id>",
  "total_cost": <float>,        // sum of est_cost across all nodes in the plan tree
  "plan": <plan_node>
}

where <plan_node> is:
{
  "op": "HashJoin" | "SeqScan" | "Filter",
  "table": "<name>",                        // SeqScan only
  "join_cond": "<left_col>=<right_col>",     // HashJoin only
  "filter_cond": "<col><op><value>",         // Filter only
  "est_card": <int>,                         // estimated output cardinality
  "est_cost": <float>,                       // this node's operator cost (NOT cumulative)
  "tables": ["<table1>", ...],               // all base tables in this subtree
  "children": [<plan_node>, ...]             // child nodes (if any)
}

For HashJoin: children[0] is the probe side (larger cardinality input),
             children[1] is the build side (smaller cardinality input).
For Filter:  children[0] is the child scan.
For SeqScan: no children.

The optimizer must:
- Apply filter pushdown: filters go directly on their base table scans,
  below any joins (not above).
- Use hash join as the physical join operator (build on smaller side).
- Enumerate valid join orderings and select the minimum total cost plan.
- Use the cost/cardinality formulas from /app/cost_formulas.py.

"""

import json
import os


def optimize_query(query: dict, catalog: dict) -> dict:
    """
    Given a query specification and catalog, return the optimal
    execution plan as a nested dictionary matching the format above.

    TODO: Implement this function.
    """
    raise NotImplementedError("Implement the query optimizer")


def compute_total_cost(plan: dict) -> float:
    """Recursively compute the total cost of a plan tree."""
    cost = plan.get("est_cost", 0)
    for child in plan.get("children", []):
        cost += compute_total_cost(child)
    return cost


def main():
    with open('/app/catalog.json') as f:
        catalog = json.load(f)
    with open('/app/queries.json') as f:
        queries = json.load(f)

    os.makedirs('/app/output', exist_ok=True)

    for query in queries:
        plan = optimize_query(query, catalog)
        total_cost = compute_total_cost(plan)
        output = {
            "query_id": query["id"],
            "total_cost": total_cost,
            "plan": plan
        }
        output_path = f'/app/output/{query["id"]}_plan.json'
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        print(f'Query {query["id"]}: total_cost={total_cost:.1f}')


if __name__ == '__main__':
    main()

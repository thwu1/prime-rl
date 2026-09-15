#!/usr/bin/env python3
"""
DP shortest path planner for CEB subset graph.
Finds optimal plan (true costs) and estimated plan (est costs),
then computes the true cost of the estimated plan.
"""


import json
import sys
from collections import defaultdict


def find_plans(data):
    edges = data["edges"]

    # Collect all nodes from edges
    nodes = set()
    for e in edges:
        nodes.add(e["sup"])
        nodes.add(e["sub"])
        nodes.add(e["diff"])

    by_size = defaultdict(list)
    for n in nodes:
        sz = len(n.split(","))
        if n not in by_size[sz]:
            by_size[sz].append(n)

    max_size = max(by_size.keys())
    final_node = by_size[max_size][0]

    # Build cost lookups
    true_costs = {}
    est_costs = {}
    for e in edges:
        key = (e["sup"], e["sub"])
        true_costs[key] = e["true_cost"]
        est_costs[key] = e["est_cost"]

    def dp_shortest(costs):
        dist = {}
        parent = {}
        # Single-table nodes connect to SOURCE with cost 1.0
        for n in by_size.get(1, []):
            dist[n] = 1.0
        sizes = sorted(by_size.keys())
        for sz in sizes:
            if sz <= 1:
                continue
            for nd in by_size[sz]:
                best = float("inf")
                bp = None
                for e in edges:
                    if e["sup"] == nd and e["sub"] in dist:
                        key = (e["sup"], e["sub"])
                        d = costs[key] + dist[e["sub"]]
                        if d < best:
                            best = d
                            bp = e["sub"]
                if bp is not None:
                    dist[nd] = best
                    parent[nd] = bp
        return dist, parent

    true_dist, _ = dp_shortest(true_costs)
    _, est_parent = dp_shortest(est_costs)

    opt_cost = true_dist[final_node] - 1.0  # Exclude SOURCE edge

    # Reconstruct estimated plan path
    path = [final_node]
    cur = final_node
    while cur in est_parent:
        cur = est_parent[cur]
        path.append(cur)

    # Compute true cost of estimated plan path
    est_plan_true_cost = 0.0
    for i in range(len(path) - 1):
        edge_key = (path[i], path[i + 1])
        if edge_key in est_costs:
            est_plan_true_cost += est_costs[edge_key]

    relative = est_plan_true_cost / opt_cost if opt_cost > 0 else float("inf")

    return {
        "name": data["name"],
        "opt_cost": round(opt_cost, 6),
        "est_cost": round(est_plan_true_cost, 6),
        "relative_cost": round(relative, 6),
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: planner.py <input.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(input_file) as f:
        data = json.load(f)

    result = find_plans(data)

    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

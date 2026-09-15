#!/usr/bin/env python3
"""
CEB-style query plan cost evaluator.

Implements the SimplePlanCost metric using cost model "C" from the
Cardinality Estimation Benchmark. Processes a single query workload
file and outputs per-query Q-Error and plan cost results.

Cost model C:
  For each edge in the subset graph (superset -> subset), the cost
  of joining the subset with the newly added table (diff) is:
    - NILJ: one side scanned fully, other probed via index (0.001x)
    - Hash join: product of cardinalities
    - Edge cost = min(NILJ, hash_join)
"""


import json
import sys
from collections import defaultdict

NILJ_CONSTANT = 0.001


def compute_edge_cost(card_node1, card_node2, len_node1, len_node2):
    """Compute edge cost using cost model C.

    Parameters
    ----------
    card_node1 : float
        Cardinality of node1 (the subset / existing subplan).
    card_node2 : float
        Cardinality of node2 (the diff / newly joined single table).
    len_node1 : int
        Number of tables in node1.
    len_node2 : int
        Number of tables in node2.

    Returns
    -------
    float
        The edge cost (minimum of NILJ and hash join).
    """
    if len_node1 == 1:
        # node1 is a single table
        nilj_cost = card_node1 + NILJ_CONSTANT * card_node2
    elif len_node2 == 1:
        # node2 is a single table
        nilj_cost = card_node2 + NILJ_CONSTANT * card_node1
    else:
        raise ValueError("Cost model C requires one node to be a single table (left-deep plans only)")

    hash_cost = card_node1 * card_node2
    return min(nilj_cost, hash_cost)


def compute_qerror(actual, estimated):
    """Compute Q-Error between actual and estimated cardinality.

    Q-Error = max(actual/estimated, estimated/actual).
    """
    return max(actual / estimated, estimated / actual)


def build_subset_graph_edges(subplan_keys):
    """Build DAG edges for the subset graph.

    Edges go from size-N subsets to size-(N-1) subsets where
    the smaller is a proper subset of the larger.
    """
    by_size = defaultdict(list)
    for key in subplan_keys:
        parts = tuple(key.split(","))
        by_size[len(parts)].append(parts)

    edges = []
    sizes = sorted(by_size.keys())
    for size in sizes:
        if size <= 1:
            continue
        prev_size = size - 1
        if prev_size not in by_size:
            continue
        for superset in by_size[size]:
            super_set = set(superset)
            for subset in by_size[prev_size]:
                if set(subset) < super_set:
                    edges.append((superset, subset))
    return edges, by_size


def compute_all_edge_costs(sg_edges, subplan_tuples, use_estimated=False):
    """Compute edge costs for all edges in the subset graph."""
    costs = {}
    card_key = "estimated" if use_estimated else "actual"
    for superset, subset in sg_edges:
        diff = tuple(sorted(set(superset) - set(subset)))
        c1 = max(subplan_tuples[subset][card_key], 1)
        c2 = max(subplan_tuples[diff][card_key], 1)
        costs[(superset, subset)] = compute_edge_cost(c1, c2, len(subset), len(diff))
    return costs


def find_shortest_path_dp(by_size, sg_edges, edge_costs):
    """Find shortest path from final node to SOURCE using DP.

    SOURCE connects to each single-table node with edge cost 1.0.
    Returns (dist, parent) where dist includes SOURCE edge cost.
    """
    dist = {}
    parent = {}

    # Single-table nodes connect to SOURCE with cost 1.0
    for node in by_size.get(1, []):
        dist[node] = 1.0

    sizes = sorted(by_size.keys())
    for size in sizes:
        if size <= 1:
            continue
        for node in by_size[size]:
            best_cost = float('inf')
            best_child = None
            for sup, sub in sg_edges:
                if sup == node and sub in dist:
                    total = edge_costs.get((sup, sub), float('inf')) + dist[sub]
                    if total < best_cost:
                        best_cost = total
                        best_child = sub
            if best_child is not None:
                dist[node] = best_cost
                parent[node] = best_child

    return dist, parent


def reconstruct_path(final_node, parent):
    """Reconstruct path from final node to the last single-table node."""
    path = [final_node]
    current = final_node
    while current in parent:
        current = parent[current]
        path.append(current)
    return path


def evaluate_query(query_data):
    """Evaluate a single query: compute Q-Errors and plan costs."""
    subplans = query_data["subplans"]

    # Parse subplan keys into tuples
    subplan_tuples = {}
    for key, cards in subplans.items():
        parts = tuple(key.split(","))
        subplan_tuples[parts] = cards

    # Build subset graph
    sg_edges, by_size = build_subset_graph_edges(list(subplans.keys()))

    # Find final node (largest subset)
    max_size = max(by_size.keys())
    final_node = by_size[max_size][0]

    # Compute edge costs
    true_costs = compute_all_edge_costs(sg_edges, subplan_tuples, use_estimated=False)
    est_costs = compute_all_edge_costs(sg_edges, subplan_tuples, use_estimated=True)

    # Find optimal plan (using true cardinalities)
    true_dist, true_parent = find_shortest_path_dp(by_size, sg_edges, true_costs)
    opt_cost = true_dist[final_node] - 1.0  # Exclude SOURCE edge

    # Find estimated plan (using estimated cardinalities)
    est_dist, est_parent = find_shortest_path_dp(by_size, sg_edges, est_costs)
    est_path = reconstruct_path(final_node, est_parent)

    # Compute TRUE cost of the estimated plan path
    est_plan_true_cost = 0.0
    for i in range(len(est_path) - 1):
        edge = (est_path[i], est_path[i + 1])
        if edge in est_costs:
            est_plan_true_cost += est_costs[edge]

    # Compute Q-Errors for all subplans
    qerrors = []
    for key, cards in subplans.items():
        qe = compute_qerror(cards["actual"], cards["estimated"])
        qerrors.append({"subplan": key, "qerror": round(qe, 6)})

    relative_cost = est_plan_true_cost / opt_cost if opt_cost > 0 else float('inf')

    return {
        "name": query_data["name"],
        "qerrors": qerrors,
        "opt_cost": round(opt_cost, 6),
        "est_cost": round(est_plan_true_cost, 6),
        "relative_cost": round(relative_cost, 6)
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: evaluator.py <query_json> <output_json>", file=sys.stderr)
        sys.exit(1)

    query_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(query_file) as f:
        query_data = json.load(f)

    result = evaluate_query(query_data)

    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

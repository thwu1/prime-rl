
"""
Reference solver for the stochastic traffic engineering problem.

Approach:
1. Compute exact Poisson binomial safe capacities per link.
2. Enumerate simple paths per demand via DFS.
3. Formulate and solve a multi-commodity flow LP.
4. Output solution.json.
"""

import json
import sys
from collections import defaultdict
from scipy.optimize import linprog


def load_data():
    with open("/app/topology.json") as f:
        topo = json.load(f)
    with open("/app/demands.json") as f:
        demands = json.load(f)
    with open("/app/config.json") as f:
        config = json.load(f)
    return topo, demands, config


def build_graph(topo):
    adj = defaultdict(list)
    link_map = {}
    edge_to_link = {}
    for link in topo["links"]:
        lid = link["id"]
        u, v = link["endpoints"]
        adj[u].append((v, lid))
        adj[v].append((u, lid))
        link_map[lid] = link
        edge_to_link[(u, v)] = lid
        edge_to_link[(v, u)] = lid
    return adj, link_map, edge_to_link


def compute_safe_capacity(wavelengths, alpha):
    """Compute largest f such that P(C >= f) >= alpha via exact enumeration."""
    k = len(wavelengths)
    cap_prob = defaultdict(float)
    for mask in range(2**k):
        cap = 0
        prob = 1.0
        for i in range(k):
            if mask & (1 << i):
                cap += wavelengths[i]["capacity"]
                prob *= 1.0 - wavelengths[i]["failure_prob"]
            else:
                prob *= wavelengths[i]["failure_prob"]
        cap_prob[cap] += prob

    caps_desc = sorted(cap_prob.keys(), reverse=True)
    cum_prob = 0.0
    for cap in caps_desc:
        cum_prob += cap_prob[cap]
        if cum_prob >= alpha:
            return cap
    return 0


def find_simple_paths(adj, src, dst, max_hops=6, max_paths=20):
    """Find simple paths using DFS with backtracking, sorted by hop count."""
    all_paths = []

    def dfs(node, path, visited):
        if len(all_paths) >= max_paths * 5:
            return
        if node == dst:
            all_paths.append(list(path))
            return
        if len(path) > max_hops:
            return
        for neighbor, lid in sorted(adj[node]):
            if neighbor not in visited:
                path.append(neighbor)
                visited.add(neighbor)
                dfs(neighbor, path, visited)
                path.pop()
                visited.discard(neighbor)

    dfs(src, [src], {src})
    all_paths.sort(key=len)
    return all_paths[:max_paths]


def solve():
    topo, demands_data, config = load_data()
    alpha = config["availability"]
    adj, link_map, edge_to_link = build_graph(topo)

    # Step 1: Compute safe capacities
    safe_caps = {}
    for lid, link in link_map.items():
        safe_caps[lid] = compute_safe_capacity(link["wavelengths"], alpha)
        print(f"  Link {lid}: safe_cap = {safe_caps[lid]}", file=sys.stderr)

    # Step 2: Find paths per demand
    demand_paths = {}
    for d in demands_data["demands"]:
        paths = find_simple_paths(adj, d["source"], d["destination"])
        demand_paths[d["id"]] = paths
        print(
            f"  Demand {d['id']} ({d['source']}->{d['destination']}): "
            f"{len(paths)} paths found",
            file=sys.stderr,
        )

    # Step 3: Build LP
    var_info = []  # (demand_id, path_index, path_nodes, link_ids)
    for d in demands_data["demands"]:
        did = d["id"]
        for pi, path in enumerate(demand_paths[did]):
            plinks = []
            for i in range(len(path) - 1):
                plinks.append(edge_to_link[(path[i], path[i + 1])])
            var_info.append((did, pi, path, plinks))

    n_vars = len(var_info)
    if n_vars == 0:
        print("ERROR: No paths found for any demand", file=sys.stderr)
        return

    # Objective: maximize sum of flows -> minimize -sum
    c = [-1.0] * n_vars

    # Inequality constraints
    A_ub = []
    b_ub = []

    demand_vols = {d["id"]: d["volume"] for d in demands_data["demands"]}
    demand_ids = [d["id"] for d in demands_data["demands"]]

    # Per-demand volume constraints
    for did in demand_ids:
        row = [1.0 if var_info[i][0] == did else 0.0 for i in range(n_vars)]
        A_ub.append(row)
        b_ub.append(float(demand_vols[did]))

    # Per-link safe capacity constraints
    all_link_ids = list(link_map.keys())
    for lid in all_link_ids:
        row = [1.0 if lid in var_info[i][3] else 0.0 for i in range(n_vars)]
        if any(r > 0 for r in row):
            A_ub.append(row)
            b_ub.append(float(safe_caps[lid]))

    bounds = [(0, None)] * n_vars

    # Step 4: Solve LP
    result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

    if not result.success:
        print(f"ERROR: LP failed: {result.message}", file=sys.stderr)
        return

    total_flow = -result.fun
    print(f"\nOptimal total flow: {total_flow:.2f} Gbps", file=sys.stderr)

    # Step 5: Build solution
    allocations_by_demand = defaultdict(list)
    for i, (did, pi, path, plinks) in enumerate(var_info):
        flow = result.x[i]
        if flow > 0.01:
            allocations_by_demand[did].append(
                {"nodes": path, "flow": round(flow, 4)}
            )

    solution = {
        "allocations": [
            {
                "demand_id": did,
                "paths": allocations_by_demand.get(did, []),
            }
            for did in demand_ids
        ]
    }

    with open("/app/solution.json", "w") as f:
        json.dump(solution, f, indent=2)

    # Print summary
    for did in demand_ids:
        total_d = sum(p["flow"] for p in allocations_by_demand.get(did, []))
        vol = demand_vols[did]
        print(
            f"  Demand {did}: {total_d:.2f}/{vol} Gbps "
            f"({100*total_d/vol:.1f}%)",
            file=sys.stderr,
        )

    print(f"\nSolution written to /app/solution.json", file=sys.stderr)


if __name__ == "__main__":
    solve()

#!/usr/bin/env python3
"""
Min-Cost Maximum Flow solver with node capacities.

Approach:
1. Node-splitting transform: each node v with capacity c becomes
   v_in (2*v) and v_out (2*v+1) connected by an internal edge
   of capacity c and cost 0. Source/sink get effectively infinite
   internal capacity.
2. Successive Shortest Paths (SSP) algorithm: repeatedly find the
   shortest (minimum cost) augmenting path from source to sink in the
   residual graph using SPFA (Bellman-Ford with queue), then augment
   flow along it.
3. SPFA handles negative-cost reverse edges in the residual graph
   correctly (unlike Dijkstra, which cannot).
4. Terminates when no s-t path exists in the residual graph.
"""

import json
from collections import deque, defaultdict


def solve_mcmf(num_nodes, source, sink, node_capacities, edges):
    INF = float("inf")
    BIG = 10**9

    # Node splitting: v -> v_in=2v, v_out=2v+1
    n = 2 * num_nodes
    s = 2 * source
    t = 2 * sink + 1

    # Adjacency list: each entry is [to, cap, cost, flow, rev_idx]
    graph = [[] for _ in range(n)]

    def add_edge(u, v, cap, cost):
        graph[u].append([v, cap, cost, 0, len(graph[v])])
        graph[v].append([u, 0, -cost, 0, len(graph[u]) - 1])

    # Internal edges for node splitting
    for v in range(num_nodes):
        cap = node_capacities.get(v, BIG)
        add_edge(2 * v, 2 * v + 1, cap, 0)

    # Original edges: u_out -> v_in
    original_edge_info = []
    for edge in edges:
        u, v = edge["from"], edge["to"]
        cap, cost = edge["capacity"], edge["cost"]
        u_out = 2 * u + 1
        v_in = 2 * v
        idx = len(graph[u_out])
        add_edge(u_out, v_in, cap, cost)
        original_edge_info.append((u, v, u_out, idx))

    # Successive Shortest Paths with SPFA
    total_flow = 0
    total_cost = 0

    while True:
        # SPFA to find shortest path s -> t in residual graph
        dist = [INF] * n
        dist[s] = 0
        in_queue = [False] * n
        parent = [(-1, -1)] * n

        q = deque([s])
        in_queue[s] = True

        while q:
            u = q.popleft()
            in_queue[u] = False
            for i, (v, cap, cost, flow, _) in enumerate(graph[u]):
                if cap - flow > 0 and dist[u] + cost < dist[v]:
                    dist[v] = dist[u] + cost
                    parent[v] = (u, i)
                    if not in_queue[v]:
                        q.append(v)
                        in_queue[v] = True

        if dist[t] == INF:
            break

        # Find bottleneck
        bottleneck = BIG
        v = t
        while v != s:
            u, i = parent[v]
            bottleneck = min(bottleneck, graph[u][i][1] - graph[u][i][3])
            v = u

        # Augment
        v = t
        while v != s:
            u, i = parent[v]
            graph[u][i][3] += bottleneck
            rev_i = graph[u][i][4]
            graph[v][rev_i][3] -= bottleneck
            v = u

        total_flow += bottleneck
        total_cost += bottleneck * dist[t]

    # Extract edge flows for original edges
    edge_flows = {}
    for u_orig, v_orig, node, idx in original_edge_info:
        flow = graph[node][idx][3]
        if flow > 0:
            edge_flows[f"{u_orig},{v_orig}"] = flow

    return total_flow, total_cost, edge_flows


def main():
    with open("/app/network_data.json", "r") as f:
        data = json.load(f)

    results = {"test_cases": []}

    for tc in data["test_cases"]:
        node_caps = {int(k): v for k, v in tc.get("node_capacities", {}).items()}

        max_flow, min_cost, edge_flows = solve_mcmf(
            tc["num_nodes"],
            tc["source"],
            tc["sink"],
            node_caps,
            tc["edges"],
        )

        results["test_cases"].append(
            {
                "name": tc["name"],
                "max_flow": max_flow,
                "min_cost": min_cost,
                "edge_flows": edge_flows,
            }
        )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()

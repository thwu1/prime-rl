#!/usr/bin/env python3
"""
Network path computation engine.

Reads /app/topology.json and writes /app/results.json with:
- Reachability matrix (VLAN-aware)
- Multi-metric optimal paths (hops, latency, bandwidth)
- Traffic demand feasibility analysis (individual + concurrent)
"""

import json
import heapq
from collections import defaultdict


def load_topology(path="/app/topology.json"):
    with open(path) as f:
        return json.load(f)


def build_graph(topo):
    """Build adjacency list from topology, excluding down links."""
    adj = defaultdict(list)
    link_props = {}

    for link in topo["links"]:
        if not link["up"]:
            continue
        a, b = link["src"], link["dst"]
        bw = link["bw_mbps"]
        delay = link["delay_ms"]
        adj[a].append((b, bw, delay))
        adj[b].append((a, bw, delay))
        key = tuple(sorted([a, b]))
        link_props[key] = {"bw": bw, "delay": delay}

    return adj, link_props


def dijkstra_hops(adj, src):
    """Shortest path by hop count (BFS-like Dijkstra with unit weights)."""
    dist = {src: 0}
    prev = {src: None}
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, _bw, _delay in adj[u]:
            nd = d + 1
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def dijkstra_latency(adj, src):
    """Shortest path by total link delay."""
    dist = {src: 0.0}
    prev = {src: None}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, _bw, delay in adj[u]:
            nd = d + delay
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def dijkstra_bandwidth(adj, src):
    """Widest path: maximize the minimum (bottleneck) bandwidth."""
    dist = {src: float("inf")}
    prev = {src: None}
    pq = [(-float("inf"), src)]  # negate for max-heap via min-heap
    while pq:
        neg_d, u = heapq.heappop(pq)
        d = -neg_d
        if d < dist.get(u, 0):
            continue
        for v, bw, _delay in adj[u]:
            nd = min(d, bw)
            if nd > dist.get(v, 0):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (-nd, v))
    return dist, prev


def reconstruct_path(prev, target):
    """Trace back through prev pointers to reconstruct path."""
    if target not in prev:
        return None
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = prev.get(node)
    return list(reversed(path))


def main():
    topo = load_topology()
    adj, link_props = build_graph(topo)

    # Classify nodes
    hosts = []
    host_vlan = {}
    routers = []
    all_nodes = set()

    for node in topo["nodes"]:
        name = node["name"]
        all_nodes.add(name)
        if node["type"] == "host":
            hosts.append(name)
            host_vlan[name] = node["vlan"]
        elif node["type"] == "router":
            routers.append(name)

    router = routers[0] if routers else None

    # Precompute all-sources Dijkstra for each metric
    all_hops_dist, all_hops_prev = {}, {}
    all_lat_dist, all_lat_prev = {}, {}
    all_bw_dist, all_bw_prev = {}, {}

    for n in all_nodes:
        d, p = dijkstra_hops(adj, n)
        all_hops_dist[n], all_hops_prev[n] = d, p
        d, p = dijkstra_latency(adj, n)
        all_lat_dist[n], all_lat_prev[n] = d, p
        d, p = dijkstra_bandwidth(adj, n)
        all_bw_dist[n], all_bw_prev[n] = d, p

    # Build results
    results = {
        "reachability": {h: {} for h in hosts},
        "paths": {},
        "demand_analysis": {"demands": [], "concurrent_feasible": False},
    }

    for h1 in hosts:
        for h2 in hosts:
            if h1 == h2:
                continue

            key = f"{h1}->{h2}"
            same_vlan = host_vlan[h1] == host_vlan[h2]

            if same_vlan:
                # Same VLAN: direct path in full graph
                if h2 not in all_hops_dist[h1]:
                    results["reachability"][h1][h2] = False
                    continue

                results["reachability"][h1][h2] = True

                path_h = reconstruct_path(all_hops_prev[h1], h2)
                path_l = reconstruct_path(all_lat_prev[h1], h2)
                path_b = reconstruct_path(all_bw_prev[h1], h2)

                results["paths"][key] = {
                    "shortest_hops": {
                        "path": path_h,
                        "hops": all_hops_dist[h1][h2],
                    },
                    "min_latency": {
                        "path": path_l,
                        "latency_ms": round(all_lat_dist[h1][h2], 4),
                    },
                    "max_bandwidth": {
                        "path": path_b,
                        "bandwidth_mbps": all_bw_dist[h1][h2],
                    },
                }
            else:
                # Different VLAN: must route through router
                if router is None:
                    results["reachability"][h1][h2] = False
                    continue
                if (
                    router not in all_hops_dist[h1]
                    or h2 not in all_hops_dist[router]
                ):
                    results["reachability"][h1][h2] = False
                    continue

                results["reachability"][h1][h2] = True

                # Shortest hops through router
                path_h1r = reconstruct_path(all_hops_prev[h1], router)
                path_rh2 = reconstruct_path(all_hops_prev[router], h2)
                full_path_h = path_h1r + path_rh2[1:]
                total_hops = all_hops_dist[h1][router] + all_hops_dist[router][h2]

                # Min latency through router
                path_l1r = reconstruct_path(all_lat_prev[h1], router)
                path_lr2 = reconstruct_path(all_lat_prev[router], h2)
                full_path_l = path_l1r + path_lr2[1:]
                total_lat = all_lat_dist[h1][router] + all_lat_dist[router][h2]

                # Max bandwidth through router
                path_b1r = reconstruct_path(all_bw_prev[h1], router)
                path_br2 = reconstruct_path(all_bw_prev[router], h2)
                full_path_b = path_b1r + path_br2[1:]
                total_bw = min(
                    all_bw_dist[h1][router], all_bw_dist[router][h2]
                )

                results["paths"][key] = {
                    "shortest_hops": {
                        "path": full_path_h,
                        "hops": total_hops,
                    },
                    "min_latency": {
                        "path": full_path_l,
                        "latency_ms": round(total_lat, 4),
                    },
                    "max_bandwidth": {
                        "path": full_path_b,
                        "bandwidth_mbps": total_bw,
                    },
                }

    # --- Demand analysis ---
    link_utilization = defaultdict(float)

    for demand in topo["demands"]:
        src, dst = demand["src"], demand["dst"]
        rate = demand["rate_mbps"]
        d_key = f"{src}->{dst}"

        if d_key not in results["paths"]:
            results["demand_analysis"]["demands"].append(
                {
                    "src": src,
                    "dst": dst,
                    "rate_mbps": rate,
                    "feasible": False,
                    "bottleneck_bw_mbps": 0,
                }
            )
            continue

        # Use shortest-hop path for routing
        path = results["paths"][d_key]["shortest_hops"]["path"]

        # Compute bottleneck BW along the path
        bottleneck_bw = float("inf")
        for i in range(len(path) - 1):
            lk = tuple(sorted([path[i], path[i + 1]]))
            bw = link_props[lk]["bw"]
            if bw < bottleneck_bw:
                bottleneck_bw = bw

        feasible = rate <= bottleneck_bw

        results["demand_analysis"]["demands"].append(
            {
                "src": src,
                "dst": dst,
                "rate_mbps": rate,
                "feasible": feasible,
                "bottleneck_bw_mbps": bottleneck_bw,
            }
        )

        if feasible:
            # Accumulate link utilization (each traversal counts)
            for i in range(len(path) - 1):
                lk = tuple(sorted([path[i], path[i + 1]]))
                link_utilization[lk] += rate

    # Check concurrent feasibility across all links
    concurrent_ok = True
    for lk, util in link_utilization.items():
        if util > link_props[lk]["bw"]:
            concurrent_ok = False
            break

    results["demand_analysis"]["concurrent_feasible"] = concurrent_ok

    # Write output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()

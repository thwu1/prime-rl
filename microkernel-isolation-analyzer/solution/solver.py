#!/usr/bin/env python3
"""
Microkernel System Isolation Analyzer — reference solution.
Reads /app/system.json, computes information flow analysis, writes results to /app/results/.

"""

import json
import os
from collections import defaultdict, deque


def load_system(path="/app/system.json"):
    with open(path) as f:
        return json.load(f)


def compute_direct_info_flow(system):
    """Build direct information flow graph from access rights.
    Returns: dict[src_pd][dst_pd] -> sorted list of enabling resource IDs.
    """
    resource_writers = defaultdict(set)
    resource_readers = defaultdict(set)

    for ar in system["access_rights"]:
        pd = ar["pd_id"]
        res = ar["resource_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            resource_writers[res].add(pd)
        if perm in ("read", "readwrite"):
            resource_readers[res].add(pd)

    edges = defaultdict(lambda: defaultdict(list))
    all_resources = set(resource_writers.keys()) | set(resource_readers.keys())
    for res_id in all_resources:
        for writer in resource_writers[res_id]:
            for reader in resource_readers[res_id]:
                if writer != reader:
                    edges[writer][reader].append(res_id)

    # Sort resource lists and convert to regular dict
    result = {}
    for src in sorted(edges.keys()):
        result[src] = {}
        for dst in sorted(edges[src].keys()):
            result[src][dst] = sorted(edges[src][dst])
    return result


def get_adj_list(info_flow):
    """Convert info_flow dict to simple adjacency list (src -> set of dst)."""
    adj = defaultdict(set)
    for src, targets in info_flow.items():
        for dst in targets:
            adj[src].add(dst)
    return adj


def compute_reachability(adj, pds):
    """For each PD, compute set of all PDs reachable from it (including itself)."""
    reachable = {}
    for pd in pds:
        visited = {pd}
        queue = deque([pd])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(adj.get(node, set())):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        reachable[pd] = visited
    return reachable


def compute_tcb(reachable, pds):
    """TCB(pd) = all PDs that can reach pd (including itself)."""
    tcb = {}
    for pd in pds:
        tcb[pd] = sorted([other for other in pds if pd in reachable[other]])
    return tcb


def compute_impact(reachable, pds):
    """Impact(pd) = all PDs that pd can reach (including itself)."""
    return {pd: sorted(list(reachable[pd])) for pd in pds}


def bfs_shortest_path(adj, source, target):
    """BFS shortest path, iterating neighbors in sorted order for determinism."""
    if source == target:
        return [source]
    visited = {source}
    queue = deque([(source, [source])])
    while queue:
        node, path = queue.popleft()
        for neighbor in sorted(adj.get(node, set())):
            if neighbor not in visited:
                new_path = path + [neighbor]
                if neighbor == target:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))
    return None


def compute_violations(system, adj, pds):
    """Analyze isolation constraints for violations."""
    results = []
    for constraint in system["isolation_constraints"]:
        pd_a = constraint["pd_a"]
        pd_b = constraint["pd_b"]
        fwd_path = bfs_shortest_path(adj, pd_a, pd_b)
        rev_path = bfs_shortest_path(adj, pd_b, pd_a)
        violated = fwd_path is not None or rev_path is not None
        results.append({
            "pd_a": pd_a,
            "pd_b": pd_b,
            "violated": violated,
            "forward_path": fwd_path,
            "forward_length": len(fwd_path) - 1 if fwd_path else None,
            "reverse_path": rev_path,
            "reverse_length": len(rev_path) - 1 if rev_path else None,
        })
    return results


# --- Max-flow / Min-cut for resource cuts ---

class MaxFlowNetwork:
    """Max-flow network using Edmonds-Karp (BFS-based Ford-Fulkerson)."""

    def __init__(self):
        self.graph = defaultdict(lambda: defaultdict(int))  # capacity
        self.flow = defaultdict(lambda: defaultdict(int))
        self.nodes = set()

    def add_edge(self, u, v, cap):
        self.graph[u][v] += cap
        self.graph[v][u] += 0  # Ensure reverse edge exists for residual graph traversal
        self.nodes.add(u)
        self.nodes.add(v)

    def bfs_augment(self, source, sink):
        """Find augmenting path using BFS, return path and bottleneck."""
        visited = {source}
        queue = deque([(source, [source], float("inf"))])
        while queue:
            node, path, bottleneck = queue.popleft()
            for neighbor in sorted(self.graph[node].keys()):
                residual = self.graph[node][neighbor] - self.flow[node][neighbor]
                if neighbor not in visited and residual > 0:
                    new_bottleneck = min(bottleneck, residual)
                    new_path = path + [neighbor]
                    if neighbor == sink:
                        return new_path, new_bottleneck
                    visited.add(neighbor)
                    queue.append((neighbor, new_path, new_bottleneck))
        return None, 0

    def max_flow(self, source, sink):
        """Compute max flow from source to sink."""
        total_flow = 0
        while True:
            path, bottleneck = self.bfs_augment(source, sink)
            if path is None:
                break
            total_flow += bottleneck
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                self.flow[u][v] += bottleneck
                self.flow[v][u] -= bottleneck
        return total_flow

    def min_cut_set(self, source):
        """After max_flow, find nodes reachable from source in residual graph."""
        visited = {source}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for neighbor in self.graph[node]:
                residual = self.graph[node][neighbor] - self.flow[node][neighbor]
                if neighbor not in visited and residual > 0:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited


def build_flow_network(system, source_pd, sink_pd):
    """Build max-flow network for min resource cut computation.

    Each resource R is split into R_in and R_out with capacity 1.
    PD -> R_in (cap inf) for write/readwrite access.
    R_out -> PD (cap inf) for read/readwrite access.
    """
    INF = 10000
    net = MaxFlowNetwork()

    all_resources = set()
    for ar in system["access_rights"]:
        res = ar["resource_id"]
        all_resources.add(res)

    # Add resource split edges
    for res in all_resources:
        net.add_edge(f"{res}_in", f"{res}_out", 1)

    # Add PD-resource edges
    for ar in system["access_rights"]:
        pd = ar["pd_id"]
        res = ar["resource_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            net.add_edge(pd, f"{res}_in", INF)
        if perm in ("read", "readwrite"):
            net.add_edge(f"{res}_out", pd, INF)

    return net


def compute_min_cut_for_pair(system, source_pd, sink_pd):
    """Compute min resource cut from source_pd to sink_pd.
    Returns (cut_size, sorted list of cut resource IDs).
    """
    # Check if path exists first
    adj = defaultdict(set)
    resource_writers = defaultdict(set)
    resource_readers = defaultdict(set)
    for ar in system["access_rights"]:
        pd = ar["pd_id"]
        res = ar["resource_id"]
        perm = ar["permissions"]
        if perm in ("write", "readwrite"):
            resource_writers[res].add(pd)
        if perm in ("read", "readwrite"):
            resource_readers[res].add(pd)

    for res in set(resource_writers.keys()) | set(resource_readers.keys()):
        for w in resource_writers[res]:
            for r in resource_readers[res]:
                if w != r:
                    adj[w].add(r)

    # Quick reachability check
    path = bfs_shortest_path(adj, source_pd, sink_pd)
    if path is None:
        return 0, []

    net = build_flow_network(system, source_pd, sink_pd)
    flow_val = net.max_flow(source_pd, sink_pd)

    # Find cut resources: those where R_in is reachable but R_out is not
    reachable = net.min_cut_set(source_pd)
    all_resources = set()
    for ar in system["access_rights"]:
        all_resources.add(ar["resource_id"])

    cut_resources = []
    for res in sorted(all_resources):
        r_in = f"{res}_in"
        r_out = f"{res}_out"
        if r_in in reachable and r_out not in reachable:
            cut_resources.append(res)

    return flow_val, sorted(cut_resources)


def compute_min_cuts(system, violations):
    """Compute min cuts for all violated constraints."""
    results = []
    for v in violations:
        if not v["violated"]:
            continue
        fwd_size, fwd_resources = compute_min_cut_for_pair(system, v["pd_a"], v["pd_b"])
        rev_size, rev_resources = compute_min_cut_for_pair(system, v["pd_b"], v["pd_a"])
        results.append({
            "pd_a": v["pd_a"],
            "pd_b": v["pd_b"],
            "forward_cut_size": fwd_size,
            "forward_cut_resources": fwd_resources,
            "reverse_cut_size": rev_size,
            "reverse_cut_resources": rev_resources,
        })
    return results


def main():
    system = load_system()
    dna_token = system["dna_token"]
    pds = [pd["id"] for pd in system["protection_domains"]]

    # 1. Direct information flow
    info_flow = compute_direct_info_flow(system)

    # 2. Transitive analysis
    adj = get_adj_list(info_flow)
    reachable = compute_reachability(adj, pds)

    # 3. TCB and Impact
    tcb = compute_tcb(reachable, pds)
    impact = compute_impact(reachable, pds)

    # 4. Violations
    violations = compute_violations(system, adj, pds)

    # 5. Min cuts
    min_cuts = compute_min_cuts(system, violations)

    # Write outputs — each file wrapped with _instance_token and data key
    os.makedirs("/app/results", exist_ok=True)

    def write_output(filename, data):
        wrapped = {"_instance_token": dna_token, "data": data}
        with open(f"/app/results/{filename}", "w") as f:
            json.dump(wrapped, f, indent=2, sort_keys=False)

    write_output("info_flow.json", info_flow)
    write_output("tcb.json", tcb)
    write_output("impact.json", impact)
    write_output("violations.json", violations)
    write_output("min_cuts.json", min_cuts)


if __name__ == "__main__":
    main()

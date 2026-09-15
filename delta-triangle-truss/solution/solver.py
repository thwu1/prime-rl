#!/usr/bin/env python3
"""

Correct solver for the graph analytics pipeline.

This script independently computes all three outputs (triangle counts,
per-node triangle participation, truss decomposition) from the raw CSV
data using delta queries and support-based peeling, bypassing the
buggy Rust pipeline entirely.
"""
import os
import heapq
from collections import defaultdict


def load_initial_graph():
    edges = []
    with open('/data/initial_edges.csv') as f:
        f.readline()
        for line in f:
            line = line.strip()
            if line:
                u, v = line.split(',')
                edges.append((int(u), int(v)))
    return edges


def load_operations():
    batches = defaultdict(list)
    with open('/data/operations.csv') as f:
        f.readline()
        for line in f:
            line = line.strip()
            if line:
                parts = line.split(',')
                batch_id = int(parts[0])
                op = parts[1]
                u, v = int(parts[2]), int(parts[3])
                batches[batch_id].append((op, u, v))
    return batches


def compute_truss(edge_set):
    """Compute truss decomposition via support peeling."""
    edges = sorted(edge_set)

    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)

    # Compute initial per-edge support (triangle count)
    support = {}
    for u, v in edges:
        support[(u, v)] = len(adj[u] & adj[v])

    remaining = set(edges)
    truss_num = {}

    pq = [(support[e], e) for e in edges]
    heapq.heapify(pq)

    k = 2
    while pq:
        s, e = heapq.heappop(pq)
        if e not in remaining:
            continue
        if support[e] != s:
            continue  # stale heap entry

        k = max(k, s + 2)
        truss_num[e] = k

        u, v = e
        common = adj[u] & adj[v]
        for w in common:
            e1 = (min(u, w), max(u, w))
            e2 = (min(v, w), max(v, w))
            if e1 in remaining:
                support[e1] -= 1
                heapq.heappush(pq, (support[e1], e1))
            if e2 in remaining:
                support[e2] -= 1
                heapq.heappush(pq, (support[e2], e2))

        adj[u].discard(v)
        adj[v].discard(u)
        remaining.discard(e)

    return truss_num


def main():
    initial_edges = load_initial_graph()
    operations = load_operations()

    adj = defaultdict(set)
    edge_set = set()
    node_tri = defaultdict(int)
    total_tri = 0

    # Bootstrap: process initial edges via delta queries (from empty graph)
    for u, v in initial_edges:
        common = adj[u] & adj[v]
        delta = len(common)
        total_tri += delta
        node_tri[u] += delta
        node_tri[v] += delta
        for w in common:
            node_tri[w] += 1
        adj[u].add(v)
        adj[v].add(u)
        edge_set.add((u, v))

    # Process 300 batches
    num_batches = 300
    tri_results = []

    for batch_id in range(num_batches):
        ops = operations.get(batch_id, [])
        for op, u, v in ops:
            common = adj[u] & adj[v]
            delta = len(common)
            if op == '+':
                total_tri += delta
                node_tri[u] += delta
                node_tri[v] += delta
                for w in common:
                    node_tri[w] += 1
                adj[u].add(v)
                adj[v].add(u)
                edge_set.add((u, v))
            else:
                total_tri -= delta
                node_tri[u] -= delta
                node_tri[v] -= delta
                for w in common:
                    node_tri[w] -= 1
                adj[u].discard(v)
                adj[v].discard(u)
                edge_set.discard((u, v))
        tri_results.append(f"{batch_id} {total_tri}")

    # Write outputs
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/triangle_counts.txt', 'w') as f:
        f.write('\n'.join(tri_results) + '\n')

    with open('/app/output/node_triangles.txt', 'w') as f:
        for node_id in sorted(node_tri.keys()):
            if node_tri[node_id] > 0:
                f.write(f"{node_id} {node_tri[node_id]}\n")

    # Truss decomposition on final graph
    truss = compute_truss(edge_set)

    with open('/app/output/truss_decomposition.txt', 'w') as f:
        for edge in sorted(truss.keys()):
            u, v = edge
            f.write(f"{u} {v} {truss[edge]}\n")


if __name__ == '__main__':
    main()

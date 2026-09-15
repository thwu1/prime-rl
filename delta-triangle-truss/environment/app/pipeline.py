#!/usr/bin/env python3
"""
Graph analytics pipeline.

Reads dynamic graph data from CSV files, computes incremental triangle
analytics as the graph evolves through batched edge operations, and
writes results to /app/output/.
"""
import json
import os
import sys
from collections import defaultdict

from analytics.graph import Graph
from analytics.incremental import IncrementalTriangleCounting
from analytics.truss import compute_truss_decomposition


def load_config():
    """Load pipeline configuration from config.json."""
    with open('/app/config.json') as f:
        return json.load(f)


def load_edges(path):
    """Load an edge list from a CSV file (expects header row)."""
    edges = []
    with open(path) as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if line:
                u, v = line.split(',')
                edges.append((int(u), int(v)))
    return edges


def load_operations(path):
    """Load batched edge operations from a CSV file, grouped by batch_id."""
    batches = defaultdict(list)
    with open(path) as f:
        f.readline()  # skip header
        for line in f:
            line = line.strip()
            if line:
                parts = line.split(',')
                batch_id = int(parts[0])
                op = parts[1]
                u, v = int(parts[2]), int(parts[3])
                batches[batch_id].append((op, u, v))
    return batches


def main():
    config = load_config()

    initial_edges = load_edges(config['initial_edges_path'])
    operations = load_operations(config['operations_path'])
    num_batches = config['num_batches']

    print(f"Loaded {len(initial_edges)} initial edges")

    # Initialize graph and incremental analytics
    graph = Graph()
    counter = IncrementalTriangleCounting(graph)

    # Bootstrap from initial edge set
    counter.bootstrap(initial_edges)
    print(f"After bootstrap: {counter.total_tri} triangles, "
          f"{graph.num_edges()} edges")

    # Process operation batches
    triangle_counts = []
    for batch_id in range(num_batches):
        ops = operations.get(batch_id, [])
        for op, u, v in ops:
            counter.apply_operation(op, u, v)
        triangle_counts.append((batch_id, counter.total_tri))

        if (batch_id + 1) % 100 == 0:
            print(f"  Batch {batch_id}: triangles={counter.total_tri}, "
                  f"edges={graph.num_edges()}")

    # Write triangle counts
    os.makedirs('/app/output', exist_ok=True)

    with open('/app/output/triangle_counts.txt', 'w') as f:
        for bid, count in triangle_counts:
            f.write(f"{bid} {count}\n")
    print(f"Wrote triangle_counts.txt ({len(triangle_counts)} entries)")

    # Write per-node triangle participation
    node_tri = counter.get_node_triangles()
    with open('/app/output/node_triangles.txt', 'w') as f:
        for node_id in sorted(node_tri.keys()):
            f.write(f"{node_id} {node_tri[node_id]}\n")
    print(f"Wrote node_triangles.txt ({len(node_tri)} nodes)")

    # Truss decomposition on the final graph
    try:
        truss = compute_truss_decomposition(graph)
        with open('/app/output/truss_decomposition.txt', 'w') as f:
            for (u, v), k in sorted(truss.items()):
                f.write(f"{u} {v} {k}\n")
        print(f"Wrote truss_decomposition.txt ({len(truss)} edges)")
    except NotImplementedError as e:
        print(f"SKIPPED: {e}", file=sys.stderr)
        # Write empty file so pipeline does not fail entirely
        with open('/app/output/truss_decomposition.txt', 'w') as f:
            pass

    print("Pipeline complete.")


if __name__ == '__main__':
    main()

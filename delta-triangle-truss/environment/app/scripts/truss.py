#!/usr/bin/env python3
"""
Truss decomposition of a graph.

Reads an edge list file and outputs truss numbers for each edge.
The truss number of an edge (u, v) is the maximum k such that (u, v)
belongs to a k-truss: a maximal subgraph where every edge participates
in at least (k - 2) triangles within that subgraph.
"""
import sys


def compute_truss_decomposition(edges):
    """Compute truss number for each edge via support-based peeling.

    Args:
        edges: list of (u, v) tuples with u < v

    Returns:
        dict mapping (u, v) to truss number
    """
    raise NotImplementedError(
        "Truss decomposition has not been implemented. "
        "See SPEC.md for the mathematical definition."
    )


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <edges_file> <output_file>", file=sys.stderr)
        sys.exit(1)

    edges_file = sys.argv[1]
    output_file = sys.argv[2]

    edges = []
    with open(edges_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                edges.append((u, v))

    truss = compute_truss_decomposition(edges)

    with open(output_file, 'w') as f:
        for (u, v), k in sorted(truss.items()):
            f.write(f"{u} {v} {k}\n")


if __name__ == '__main__':
    main()

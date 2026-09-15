#!/usr/bin/env python3
"""
Computes the Maximum Clique Number (MCN) of the disjointness graph
of unavoidable sets using the Bron-Kerbosch algorithm.

Usage: python3 clique_finder.py <sets.json>
Output: JSON with mcn, max_clique_indices, clique_counts

"""
import sys
import json
from itertools import combinations


def build_disjointness_adj(sets):
    """Build adjacency list for the disjointness graph.
    Edge (i,j) exists iff sets i and j share no common cells."""
    n = len(sets)
    adj = [set() for _ in range(n)]
    for i in range(n):
        si = set(sets[i])
        for j in range(i + 1, n):
            if si & set(sets[j]):
                adj[i].add(j)
                adj[j].add(i)
    return adj


def max_clique_bk(adj, n):
    """Bron-Kerbosch with pivoting for maximum clique."""
    best = []

    def bk(R, P, X):
        nonlocal best
        if not P and not X:
            if len(R) > len(best):
                best = list(R)
            return
        if not P:
            return
        pivot = max(P | X, key=lambda v: len(adj[v] & P))
        for v in sorted(P - adj[pivot]):
            bk(R | {v}, P & adj[v], X & adj[v])
            P -= {v}
            X |= {v}

    bk(set(), set(range(n)), set())
    return best


def count_cliques(adj, n, target):
    """Count all cliques of a given size."""
    count = [0]

    def enum(clique, cands, minv):
        if len(clique) == target:
            count[0] += 1
            return
        rem = target - len(clique)
        cs = sorted(v for v in cands if v >= minv)
        for idx, v in enumerate(cs):
            if len(cs) - idx < rem:
                break
            enum(clique + [v], set(cs[idx + 1:]) & adj[v], v + 1)

    enum([], set(range(n)), 0)
    return count[0]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 clique_finder.py <sets.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        sets = json.load(f)

    n = len(sets)
    print(f"Building disjointness graph for {n} sets...", file=sys.stderr)
    adj = build_disjointness_adj(sets)

    print("Finding maximum clique...", file=sys.stderr)
    mc = max_clique_bk(adj, n)

    cc = {}
    for k in range(2, 6):
        print(f"Counting cliques of size {k}...", file=sys.stderr)
        cc[str(k)] = count_cliques(adj, n, k)

    result = {
        'mcn': len(mc),
        'max_clique_indices': sorted(mc),
        'clique_counts': cc
    }
    print(json.dumps(result, indent=2))

#!/usr/bin/env python3

"""
Exact solver for One-Sided Crossing Minimization (OCM) using bitmask DP.

Reads a bipartite graph in PACE .gr format from stdin and outputs an optimal
ordering of the free partition B that minimizes edge crossings.

Algorithm: dp[S] = minimum crossings achievable by ordering the B-vertices in
subset S. Transition: for each vertex b in S, try placing b as the rightmost
vertex in the current layout and add crossing cost against all vertices in S\\{b}.

Time complexity: O(2^n1 * n1^2) where n1 = |B|.
Space complexity: O(2^n1).
"""

import sys


def main():
    lines = sys.stdin.read().strip().split('\n')

    n0 = n1 = m = 0
    edges = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith('c'):
            continue
        if line.startswith('p'):
            parts = line.split()
            n0 = int(parts[2])
            n1 = int(parts[3])
            m = int(parts[4])
        else:
            parts = line.split()
            a, b = int(parts[0]), int(parts[1])
            edges.append((a, b))

    b_vertices = list(range(n0 + 1, n0 + n1 + 1))
    b_idx = {v: i for i, v in enumerate(b_vertices)}
    n = len(b_vertices)

    # Build adjacency: for each B-vertex, its list of A-neighbors
    adj = [[] for _ in range(n)]
    for a, b in edges:
        adj[b_idx[b]].append(a)

    # Precompute cross_right[i][j]:
    # Number of crossings when b_vertices[i] is placed to the RIGHT of b_vertices[j].
    # An edge (a, bi) crosses edge (a', bj) when bi is right of bj iff a < a'.
    cross_right = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            cnt = 0
            for a in adj[i]:
                for a2 in adj[j]:
                    if a < a2:
                        cnt += 1
            cross_right[i][j] = cnt

    # Bitmask DP
    full = (1 << n) - 1
    INF = float('inf')
    dp = [INF] * (1 << n)
    parent = [-1] * (1 << n)
    dp[0] = 0

    for mask in range(1, 1 << n):
        for i in range(n):
            if not (mask & (1 << i)):
                continue
            rest = mask ^ (1 << i)
            # Cost of placing i as rightmost in mask
            cost = 0
            temp = rest
            while temp:
                j = (temp & -temp).bit_length() - 1
                cost += cross_right[i][j]
                temp &= temp - 1
            total = dp[rest] + cost
            if total < dp[mask]:
                dp[mask] = total
                parent[mask] = i

    # Reconstruct: parent[mask] is the rightmost vertex of optimal ordering of mask
    order = []
    mask = full
    while mask:
        i = parent[mask]
        order.append(b_vertices[i])
        mask ^= (1 << i)
    order.reverse()

    for v in order:
        print(v)


if __name__ == '__main__':
    main()

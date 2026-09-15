#!/usr/bin/env python3

"""
Exact solver for One-Sided Crossing Minimization using bitmask DP.

For each pair of B vertices (i, j), precompute c[i][j] = number of crossings
contributed when i is placed before j. Then use DP over subsets:
  dp[S] = minimum total crossings using the vertices in set S as the
          first |S| positions (left to right).
Transition: dp[S | {v}] = min over v not in S of dp[S] + sum_{u in S} c[u][v]

Complexity: O(2^n1 * n1^2) time and O(2^n1) space.
"""

import os
import glob
import sys


def parse_instance(filepath):
    n0 = n1 = m = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                n0, n1, m = int(parts[2]), int(parts[3]), int(parts[4])
            else:
                parts = line.split()
                edges.append((int(parts[0]), int(parts[1])))
    return n0, n1, edges


def solve(n0, n1, edges):
    B = list(range(n0 + 1, n0 + n1 + 1))
    n = len(B)

    # Build adjacency: for each B vertex, sorted list of A neighbors
    neighbors = {b: [] for b in B}
    for a, b in edges:
        neighbors[b].append(a)

    # Precompute pairwise crossing costs
    # c_idx[i][j] = crossings when B[i] is placed before B[j]
    c_idx = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                count = 0
                for a1 in neighbors[B[i]]:
                    for a2 in neighbors[B[j]]:
                        if a1 > a2:
                            count += 1
                c_idx[i][j] = count

    # Bitmask DP
    INF = float("inf")
    size = 1 << n
    dp = [INF] * size
    parent = [-1] * size
    dp[0] = 0

    for mask in range(size):
        if dp[mask] == INF:
            continue
        for v in range(n):
            if mask & (1 << v):
                continue
            # Cost of appending v after all vertices already in mask
            cost = 0
            tmp = mask
            while tmp:
                u = (tmp & -tmp).bit_length() - 1
                cost += c_idx[u][v]
                tmp &= tmp - 1
            new_mask = mask | (1 << v)
            new_cost = dp[mask] + cost
            if new_cost < dp[new_mask]:
                dp[new_mask] = new_cost
                parent[new_mask] = v

    full_mask = size - 1
    # Reconstruct permutation
    perm = []
    mask = full_mask
    while mask:
        v = parent[mask]
        perm.append(B[v])
        mask ^= 1 << v
    perm.reverse()
    return perm


def main():
    instances_dir = "/app/instances"
    solutions_dir = "/app/solutions"
    os.makedirs(solutions_dir, exist_ok=True)

    instance_files = sorted(glob.glob(os.path.join(instances_dir, "*.gr")))
    for inst_path in instance_files:
        basename = os.path.basename(inst_path).replace(".gr", "")
        sol_path = os.path.join(solutions_dir, f"{basename}.sol")

        print(f"Solving {basename}...", file=sys.stderr)
        n0, n1, edges = parse_instance(inst_path)
        perm = solve(n0, n1, edges)

        with open(sol_path, "w") as f:
            for v in perm:
                f.write(f"{v}\n")
        print(f"  Done: {sol_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

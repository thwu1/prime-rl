#!/usr/bin/env python3
"""
Symbolic Sparse Cholesky Analysis — oracle solution.

Computes symbolic Cholesky factorization under natural, AMD (greedy minimum
degree), and RCM (Reverse Cuthill-McKee) orderings for each Matrix Market
file in /app/matrices/. Produces /app/results.json.

"""

import json
import os
import glob


# ---------------------------------------------------------------------------
# Matrix Market parser
# ---------------------------------------------------------------------------

def parse_mm(path):
    """Parse Matrix Market file. Returns (n, lower_triangle_entries) 0-indexed."""
    entries = []
    n = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('%'):
                continue
            parts = line.split()
            if n is None:
                n = int(parts[0])
                continue
            r, c, v = int(parts[0]) - 1, int(parts[1]) - 1, float(parts[2])
            entries.append((r, c, v))
    return n, entries


# ---------------------------------------------------------------------------
# Graph utilities
# ---------------------------------------------------------------------------

def build_adjacency(n, entries):
    """Build symmetric adjacency from lower-triangle entries."""
    adj = [set() for _ in range(n)]
    for i, j, _ in entries:
        if i != j:
            adj[i].add(j)
            adj[j].add(i)
    return adj


def connected_components(n, adj):
    vis = [False] * n
    cnt = 0
    for i in range(n):
        if not vis[i]:
            cnt += 1
            stk = [i]
            vis[i] = True
            while stk:
                nd = stk.pop()
                for nb in adj[nd]:
                    if not vis[nb]:
                        vis[nb] = True
                        stk.append(nb)
    return cnt


# ---------------------------------------------------------------------------
# Symbolic Cholesky
# ---------------------------------------------------------------------------

def symbolic_cholesky(n, entries, perm=None):
    """Symbolic Cholesky factorization.

    perm[new_index] = old_index.
    Returns (nnz_L, parent_array, flop_count).
    nnz_L includes diagonal. flop_count = sum_j c_j*(c_j+1) where c_j =
    subdiagonal nonzeros in column j of L.
    """
    if perm is None:
        perm = list(range(n))
    inv = [0] * n
    for new_idx, old_idx in enumerate(perm):
        inv[old_idx] = new_idx

    # Build column sets (lower triangle of permuted matrix)
    cols = [set() for _ in range(n)]
    for j in range(n):
        cols[j].add(j)

    for oi, oj, _ in entries:
        ni, nj = inv[oi], inv[oj]
        if ni == nj:
            continue
        if ni > nj:
            cols[nj].add(ni)
        else:
            cols[ni].add(nj)

    # Simulate elimination: propagate fill
    for j in range(n):
        below = sorted(r for r in cols[j] if r > j)
        for r in below:
            for s in below:
                if s >= r:
                    cols[r].add(s)

    # Extract parent, nnz, flops
    parent = [-1] * n
    nnz_L = 0
    flops = 0
    for j in range(n):
        below = sorted(r for r in cols[j] if r > j)
        if below:
            parent[j] = below[0]
        c = len(below)
        flops += c * c + c
        nnz_L += 1 + c
    return nnz_L, parent, flops


def etree_height(parent):
    n = len(parent)
    if n == 0:
        return 0
    depth = [0] * n
    for i in range(n):
        j, d = i, 0
        while parent[j] != -1:
            j = parent[j]
            d += 1
            if d > n:
                break
        depth[i] = d
    return max(depth) + 1


# ---------------------------------------------------------------------------
# AMD ordering (greedy minimum degree with element absorption)
# ---------------------------------------------------------------------------

def min_degree_ordering(n, adj):
    """Greedy minimum degree ordering. Ties broken by smallest index.
    This is an exact minimum degree algorithm — the 'approximate' in AMD
    refers to degree bounds used in SuiteSparse's production implementation,
    but for small matrices the exact version is equivalent."""
    work = [set(s) for s in adj]
    done = [False] * n
    perm = []
    for _ in range(n):
        best = -1
        best_deg = n + 1
        for i in range(n):
            if not done[i]:
                deg = sum(1 for j in work[i] if not done[j])
                if deg < best_deg:
                    best_deg = deg
                    best = i
        perm.append(best)
        done[best] = True
        # Make neighbors a clique (mass elimination)
        nbrs = [j for j in work[best] if not done[j]]
        for i in range(len(nbrs)):
            for j in range(i + 1, len(nbrs)):
                work[nbrs[i]].add(nbrs[j])
                work[nbrs[j]].add(nbrs[i])
    return perm


# ---------------------------------------------------------------------------
# RCM ordering
# ---------------------------------------------------------------------------

def bfs_levels(n, adj, start):
    vis = [False] * n
    levels = []
    cur = [start]
    vis[start] = True
    while cur:
        levels.append(cur[:])
        nxt = []
        for nd in cur:
            for nb in sorted(adj[nd]):
                if not vis[nb]:
                    vis[nb] = True
                    nxt.append(nb)
        cur = nxt
    return levels


def rcm_ordering(n, adj):
    """Reverse Cuthill-McKee ordering with pseudo-peripheral start vertex."""
    # Find pseudo-peripheral starting vertex
    start = min(range(n), key=lambda i: len(adj[i]))
    for _ in range(5):
        lvs = bfs_levels(n, adj, start)
        best = min(lvs[-1], key=lambda x: len(adj[x]))
        if best == start:
            break
        start = best

    # BFS with degree-sorted neighbors
    vis = [False] * n
    order = []
    q = [start]
    vis[start] = True
    h = 0
    while h < len(q):
        nd = q[h]
        h += 1
        order.append(nd)
        for nb in sorted(adj[nd], key=lambda x: len(adj[x])):
            if not vis[nb]:
                vis[nb] = True
                q.append(nb)

    # Handle disconnected components
    for i in range(n):
        if not vis[i]:
            q.append(i)
            vis[i] = True
            while h < len(q):
                nd = q[h]
                h += 1
                order.append(nd)
                for nb in sorted(adj[nd], key=lambda x: len(adj[x])):
                    if not vis[nb]:
                        vis[nb] = True
                        q.append(nb)

    order.reverse()
    return order


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyze_matrix(path):
    name = os.path.splitext(os.path.basename(path))[0]
    n, entries = parse_mm(path)
    adj = build_adjacency(n, entries)

    result = {
        "n": n,
        "nnz_lower_A": len(entries),
        "num_components": connected_components(n, adj),
    }

    # Natural ordering (identity permutation)
    nnz_nat, par_nat, fl_nat = symbolic_cholesky(n, entries)
    result["natural"] = {
        "nnz_L": nnz_nat,
        "etree_height": etree_height(par_nat),
        "flop_count": fl_nat,
    }

    # AMD ordering (minimum degree)
    perm_amd = min_degree_ordering(n, adj)
    nnz_amd, par_amd, fl_amd = symbolic_cholesky(n, entries, perm_amd)
    result["amd"] = {
        "ordering": perm_amd,
        "nnz_L": nnz_amd,
        "etree_height": etree_height(par_amd),
        "flop_count": fl_amd,
    }

    # RCM ordering
    perm_rcm = rcm_ordering(n, adj)
    nnz_rcm, par_rcm, fl_rcm = symbolic_cholesky(n, entries, perm_rcm)
    result["rcm"] = {
        "ordering": perm_rcm,
        "nnz_L": nnz_rcm,
        "etree_height": etree_height(par_rcm),
        "flop_count": fl_rcm,
    }

    # Best ordering by nnz_L
    orderings = {
        "natural": nnz_nat,
        "amd": nnz_amd,
        "rcm": nnz_rcm,
    }
    result["best_ordering"] = min(orderings, key=orderings.get)

    return name, result


def main():
    matrix_dir = "/app/matrices"
    results = {}
    for mtx_file in sorted(glob.glob(os.path.join(matrix_dir, "*.mtx"))):
        name, result = analyze_matrix(mtx_file)
        results[name] = result
        print(f"Analyzed {name}: n={result['n']}, "
              f"natural nnz_L={result['natural']['nnz_L']}, "
              f"amd nnz_L={result['amd']['nnz_L']}, "
              f"rcm nnz_L={result['rcm']['nnz_L']}, "
              f"best={result['best_ordering']}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()

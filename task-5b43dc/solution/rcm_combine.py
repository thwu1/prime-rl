#!/usr/bin/env python3
"""

Combines CXSparse C program output (natural/AMD) with RCM ordering
computed here, producing the final results.json.
"""

import json
import os
import sys


# ---------------------------------------------------------------------------
# Parse C program output
# ---------------------------------------------------------------------------

def parse_c_output(path):
    """Parse the structured output from the C analyze program."""
    results = {}
    current = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("BEGIN "):
                current = {"name": line[6:]}
            elif line == "END":
                if current:
                    results[current["name"]] = current
                current = None
            elif current is not None:
                parts = line.split(None, 1)
                if len(parts) == 2:
                    key, val = parts
                    if key == "amd_perm":
                        current[key] = [int(x) for x in val.split()]
                    else:
                        try:
                            current[key] = int(val)
                        except ValueError:
                            current[key] = val
    return results


# ---------------------------------------------------------------------------
# Matrix Market parser
# ---------------------------------------------------------------------------

def parse_mm(path):
    entries = []
    n = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("%"):
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

def build_adj(n, entries):
    adj = [set() for _ in range(n)]
    for i, j, _ in entries:
        if i != j:
            adj[i].add(j)
            adj[j].add(i)
    return adj


def num_components(n, adj):
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
    """Reverse Cuthill-McKee ordering."""
    start = min(range(n), key=lambda i: len(adj[i]))
    for _ in range(5):
        lvs = bfs_levels(n, adj, start)
        best = min(lvs[-1], key=lambda x: len(adj[x]))
        if best == start:
            break
        start = best

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
# Symbolic Cholesky
# ---------------------------------------------------------------------------

def symbolic_cholesky(n, entries, perm):
    inv = [0] * n
    for new_idx, old_idx in enumerate(perm):
        inv[old_idx] = new_idx

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

    for j in range(n):
        below = sorted(r for r in cols[j] if r > j)
        for r in below:
            for s in below:
                if s >= r:
                    cols[r].add(s)

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
    h = 0
    for i in range(n):
        d = 0
        j = i
        while parent[j] >= 0:
            j = parent[j]
            d += 1
        if d > h:
            h = d
    return h + 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    c_output_path = sys.argv[1]
    c_data = parse_c_output(c_output_path)

    matrix_dir = "/app/matrices"
    results = {}

    for mtx_file in sorted(os.listdir(matrix_dir)):
        if not mtx_file.endswith(".mtx"):
            continue
        name = mtx_file[:-4]
        n, entries = parse_mm(os.path.join(matrix_dir, mtx_file))
        adj = build_adj(n, entries)

        cd = c_data[name]

        result = {
            "n": cd["n"],
            "nnz_lower_A": cd["nnz_lower"],
            "num_components": num_components(n, adj),
            "natural": {
                "nnz_L": cd["nat_nnz"],
                "etree_height": cd["nat_height"],
                "flop_count": cd["nat_flops"],
            },
            "amd": {
                "ordering": cd["amd_perm"],
                "nnz_L": cd["amd_nnz"],
                "etree_height": cd["amd_height"],
                "flop_count": cd["amd_flops"],
            },
        }

        # Compute RCM ordering and its symbolic Cholesky
        perm_rcm = rcm_ordering(n, adj)
        nnz_rcm, par_rcm, fl_rcm = symbolic_cholesky(n, entries, perm_rcm)
        result["rcm"] = {
            "ordering": perm_rcm,
            "nnz_L": nnz_rcm,
            "etree_height": etree_height(par_rcm),
            "flop_count": fl_rcm,
        }

        # Determine best ordering
        orderings = {
            "natural": result["natural"]["nnz_L"],
            "amd": result["amd"]["nnz_L"],
            "rcm": result["rcm"]["nnz_L"],
        }
        result["best_ordering"] = min(orderings, key=orderings.get)

        results[name] = result
        print(f"Analyzed {name}: n={result['n']}, "
              f"natural={result['natural']['nnz_L']}, "
              f"amd={result['amd']['nnz_L']}, "
              f"rcm={result['rcm']['nnz_L']}, "
              f"best={result['best_ordering']}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Reference solver for the token swapping problem on graphs.


Implements optimal algorithms for path and complete graphs,
and a correct heuristic for trees and general graphs.
"""

from collections import deque


def solve(n, edges, perm):
    """Solve the token swapping problem on graph G with target permutation."""
    if n <= 1 or perm == list(range(n)):
        return []

    adj = [[] for _ in range(n)]
    edge_set = set()
    for e in edges:
        u, v = e[0], e[1]
        adj[u].append(v)
        adj[v].append(u)
        edge_set.add((min(u, v), max(u, v)))

    m = len(edges)

    # Complete graph: n*(n-1)/2 edges
    if m == n * (n - 1) // 2:
        return _solve_complete(n, perm)

    # Tree: n-1 edges (assuming connected)
    if m == n - 1:
        deg = [len(adj[v]) for v in range(n)]
        endpoints = sum(1 for v in range(n) if deg[v] == 1)
        if endpoints == 2 and n >= 2:
            return _solve_path(n, adj, perm)
        return _solve_tree(n, adj, perm)

    # General graph: use spanning tree reduction
    return _solve_general(n, adj, perm)


def _solve_path(n, adj, perm):
    """
    Optimal solver for path graphs.

    Uses bubble sort along the canonical path ordering. The number of swaps
    equals the number of inversions in the permutation, which is the
    theoretical minimum for adjacent transpositions on a path.
    """
    # Discover the path ordering by walking from one endpoint
    start = next(v for v in range(n) if len(adj[v]) == 1)
    order = []
    visited = set()
    v = start
    while v is not None:
        order.append(v)
        visited.add(v)
        nxt = None
        for u in adj[v]:
            if u not in visited:
                nxt = u
                break
        v = nxt

    # Position of each vertex in the path ordering
    pos_in_path = [0] * n
    for i, vtx in enumerate(order):
        pos_in_path[vtx] = i

    # Destination of each token: dest[t] = vertex where token t should end up
    dest = [0] * n
    for v in range(n):
        dest[perm[v]] = v

    # Bubble sort tokens along the path by destination position
    at = list(range(n))  # at[v] = token currently at vertex v
    pos = list(range(n))  # pos[t] = current vertex of token t
    swaps = []

    changed = True
    while changed:
        changed = False
        for i in range(len(order) - 1):
            u, v = order[i], order[i + 1]
            tu, tv = at[u], at[v]
            # Swap if the left token's destination is further right
            if pos_in_path[dest[tu]] > pos_in_path[dest[tv]]:
                at[u], at[v] = tv, tu
                pos[tu], pos[tv] = v, u
                swaps.append([u, v])
                changed = True

    return swaps


def _solve_complete(n, perm):
    """
    Optimal solver for complete graphs.

    Decomposes the permutation into disjoint cycles and realizes each cycle
    with consecutive transpositions. A k-cycle requires exactly k-1 swaps,
    giving a total of n - c(perm) swaps where c is the number of cycles.
    """
    visited = [False] * n
    swaps = []
    for i in range(n):
        if visited[i] or perm[i] == i:
            visited[i] = True
            continue
        cycle = []
        j = i
        while not visited[j]:
            visited[j] = True
            cycle.append(j)
            j = perm[j]
        # Realize cycle (c0, c1, ..., c_{k-1}) with swaps
        # (c0,c1), (c1,c2), ..., (c_{k-2},c_{k-1})
        for k in range(len(cycle) - 1):
            swaps.append([cycle[k], cycle[k + 1]])
    return swaps


def _find_path_in_tree(start, end, adj, removed):
    """Find the unique path between two vertices in a tree via BFS."""
    if start == end:
        return [start]
    parent = {start: None}
    queue = deque([start])
    while queue:
        v = queue.popleft()
        if v == end:
            break
        for u in adj[v]:
            if u not in parent and not removed[u]:
                parent[u] = v
                queue.append(u)
    path = []
    v = end
    while v is not None:
        path.append(v)
        v = parent.get(v)
    path.reverse()
    return path


def _solve_tree(n, adj, perm):
    """
    Solver for tree graphs using leaf processing.

    Iteratively processes leaves: for each leaf vertex, finds the correct
    token for that leaf, brings it along the unique tree path by performing
    swaps along edges, then removes the settled leaf. This produces a
    correct (though not always strictly optimal) swap sequence.
    """
    at = list(range(n))   # at[v] = token at vertex v
    pos = list(range(n))  # pos[t] = vertex where token t currently sits
    swaps = []

    degree = [len(adj[v]) for v in range(n)]
    removed = [False] * n

    leaves = deque()
    for v in range(n):
        if degree[v] <= 1:
            leaves.append(v)

    while leaves:
        v = leaves.popleft()
        if removed[v]:
            continue

        # If this leaf already has its target token, just remove it
        if at[v] == perm[v]:
            removed[v] = True
            for u in adj[v]:
                if not removed[u]:
                    degree[u] -= 1
                    if degree[u] <= 1:
                        leaves.append(u)
            continue

        # Bring the correct token to this leaf along the tree path
        target_token = perm[v]
        source = pos[target_token]

        path = _find_path_in_tree(source, v, adj, removed)

        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            ta, tb = at[a], at[b]
            at[a], at[b] = tb, ta
            pos[ta] = b
            pos[tb] = a
            swaps.append([a, b])

        # Now at[v] == target_token; remove the leaf
        removed[v] = True
        for u in adj[v]:
            if not removed[u]:
                degree[u] -= 1
                if degree[u] <= 1:
                    leaves.append(u)

    return swaps


def _solve_general(n, adj, perm):
    """
    Solver for general connected graphs.

    Extracts a BFS spanning tree and delegates to the tree solver.
    All tree edges are graph edges, so the swap sequence is valid.
    """
    tree_adj = [[] for _ in range(n)]
    visited = [False] * n
    queue = deque([0])
    visited[0] = True
    while queue:
        v = queue.popleft()
        for u in adj[v]:
            if not visited[u]:
                visited[u] = True
                tree_adj[v].append(u)
                tree_adj[u].append(v)
                queue.append(u)

    return _solve_tree(n, tree_adj, perm)

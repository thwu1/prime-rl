#!/usr/bin/env python3
"""
Solver for the network topology link-swap optimization task.

Explores the platform environment, reads topology data from the SQLite
database, computes optimal single-link swaps to minimize diameter for
each topology, and inserts results back into the database. Also generates
the Graphviz DOT change visualization for topology 1.

Algorithm (O(N) per topology):
1. Root the tree and compute top-3 downward path lengths and subtree
   diameters bottom-up.
2. Propagate complement diameters top-down using parent up-path and
   sibling sub-diameter information.
3. For each edge removal, the optimal reconnection joins the centers
   of the two resulting subtrees, giving:
     ans = max(d_sub, d_comp, ceil(d_sub/2) + ceil(d_comp/2) + 1)
4. Pick the edge minimizing this value; find actual centers via BFS.
"""

import sqlite3
import os
from collections import deque


def bfs_farthest(start, adj, allowed):
    """BFS within allowed node set. Returns (farthest, dist, parent_map)."""
    q = deque([(start, 0)])
    vis = {start}
    pmap = {start: -1}
    far, mx = start, 0
    while q:
        u, d = q.popleft()
        if d > mx:
            mx, far = d, u
        for v in adj[u]:
            if v in allowed and v not in vis:
                vis.add(v)
                pmap[v] = u
                q.append((v, d + 1))
    return far, mx, pmap


def find_center(start, adj, allowed):
    """Find center of tree restricted to allowed node set."""
    e1, _, _ = bfs_farthest(start, adj, allowed)
    e2, _, pmap = bfs_farthest(e1, adj, allowed)
    path = []
    cur = e2
    while cur != -1:
        path.append(cur)
        cur = pmap.get(cur, -1)
    return path[len(path) // 2]


def get_subtree(root, children):
    """Collect all nodes in rooted subtree via iterative DFS."""
    s = set()
    stk = [root]
    while stk:
        u = stk.pop()
        s.add(u)
        for c in children[u]:
            stk.append(c)
    return s


def compute_diameter_bfs(adj, n):
    """Compute diameter of tree using double BFS."""
    def bfs_far(start):
        dist = [-1] * (n + 1)
        dist[start] = 0
        q = deque([start])
        far, mx = start, 0
        while q:
            u = q.popleft()
            if dist[u] > mx:
                mx, far = dist[u], u
            for v in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return far, mx
    e1, _ = bfs_far(1)
    _, diam = bfs_far(e1)
    return diam


def solve_topology(n, adj, edges):
    """Solve single-link-swap diameter minimization for one topology."""
    if n <= 2:
        e = edges[0] if edges else (1, 1)
        return n - 1, e, e

    root = 1
    par = [0] * (n + 1)
    par[root] = -1
    order = []
    vis = bytearray(n + 1)
    vis[root] = 1
    q = deque([root])
    while q:
        u = q.popleft()
        order.append(u)
        for v in adj[u]:
            if not vis[v]:
                vis[v] = 1
                par[v] = u
                q.append(v)

    ch = [[] for _ in range(n + 1)]
    for v in order[1:]:
        ch[par[v]].append(v)

    # Bottom-up DP: top-3 down paths, subtree diameters
    d1 = [0] * (n + 1)
    d2 = [0] * (n + 1)
    d3 = [0] * (n + 1)
    d1c = [0] * (n + 1)
    d2c = [0] * (n + 1)
    sd = [0] * (n + 1)

    for v in reversed(order):
        b1 = b2 = b3 = 0
        c1 = c2 = 0
        mxsd = 0
        for c in ch[v]:
            val = d1[c] + 1
            if sd[c] > mxsd:
                mxsd = sd[c]
            if val > b1:
                b3, b2, c2, b1, c1 = b2, b1, c1, val, c
            elif val > b2:
                b3, b2, c2 = b2, val, c
            elif val > b3:
                b3 = val
        d1[v], d1c[v] = b1, c1
        d2[v], d2c[v] = b2, c2
        d3[v] = b3
        sd[v] = max(mxsd, b1 + b2)

    # Max sub-diameter among children (top-2)
    sm1 = [0] * (n + 1)
    sm1c = [0] * (n + 1)
    sm2 = [0] * (n + 1)
    for v in order:
        b1 = b2 = 0
        c1 = 0
        for c in ch[v]:
            if sd[c] >= b1:
                b2, b1, c1 = b1, sd[c], c
            elif sd[c] > b2:
                b2 = sd[c]
        sm1[v], sm1c[v], sm2[v] = b1, c1, b2

    # Top-down DP: up paths, complement diameters
    up = [0] * (n + 1)
    cd = [0] * (n + 1)

    for v in order:
        if par[v] == -1:
            continue
        p = par[v]
        bd = d2[p] if d1c[p] == v else d1[p]
        up[v] = 1 + max(up[p], bd)

        if d1c[p] == v:
            t1, t2 = d2[p], d3[p]
        elif d2c[p] == v:
            t1, t2 = d1[p], d3[p]
        else:
            t1, t2 = d1[p], d2[p]

        ssd = sm2[p] if sm1c[p] == v else sm1[p]
        cd[v] = max(cd[p], up[p] + bd, t1 + t2, ssd)

    # Find best edge to remove
    best_ans = float('inf')
    best_v = -1
    for v in order[1:]:
        ds, dc = sd[v], cd[v]
        ans = max(ds, dc, (ds + 1) // 2 + (dc + 1) // 2 + 1)
        if ans < best_ans:
            best_ans, best_v = ans, v

    # Identify the original edge to remove
    rp, rv = par[best_v], best_v
    rem = None
    for u, w in edges:
        if (u == rp and w == rv) or (u == rv and w == rp):
            rem = (u, w)
            break

    # Find centers of both components for optimal reconnection
    sub_nodes = get_subtree(rv, ch)
    comp_nodes = set(range(1, n + 1)) - sub_nodes
    c_sub = find_center(rv, adj, sub_nodes)
    c_comp = find_center(rp, adj, comp_nodes)

    return best_ans, rem, (c_sub, c_comp)


def generate_dot_file(n, edges, removed, added, name, path):
    """Generate Graphviz DOT file for topology change visualization."""
    lines = [f'graph {name} {{']
    for u, v in edges:
        if (u == removed[0] and v == removed[1]) or \
           (u == removed[1] and v == removed[0]):
            lines.append(f'  {u} -- {v} [style=dashed color=red];')
        else:
            lines.append(f'  {u} -- {v};')
    lines.append(f'  {added[0]} -- {added[1]} [style=bold color=green];')
    lines.append('}')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    db_path = '/app/netops.db'
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Ensure original_diameter column exists
    try:
        cur.execute("ALTER TABLE optimization_results ADD COLUMN original_diameter INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Read all topologies
    cur.execute('SELECT topology_id, name, node_count FROM topologies ORDER BY topology_id')
    topos = cur.fetchall()

    os.makedirs('/app/reports', exist_ok=True)

    for tid, tname, n in topos:
        cur.execute('SELECT src_node, dst_node FROM links WHERE topology_id = ?', (tid,))
        edges = [(r[0], r[1]) for r in cur.fetchall()]

        adj = [[] for _ in range(n + 1)]
        for u, v in edges:
            adj[u].append(v)
            adj[v].append(u)

        # Compute original diameter
        orig_diam = compute_diameter_bfs(adj, n)

        # Compute optimal swap
        diam, rem, add_edge = solve_topology(n, adj, edges)

        cur.execute('''INSERT OR REPLACE INTO optimization_results
                       (topology_id, min_diameter, remove_src, remove_dst,
                        add_src, add_dst, original_diameter)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (tid, diam, rem[0], rem[1], add_edge[0], add_edge[1], orig_diam))

        # Generate DOT file for topology 1 (branch_office_alpha)
        if tid == 1:
            generate_dot_file(n, edges, rem, add_edge, tname,
                              '/app/reports/topology_changes.dot')

        print(f"Topology {tid} ({tname}): original_diameter={orig_diam}, optimal={diam}")

    conn.commit()
    conn.close()
    print("All topologies optimized.")


if __name__ == '__main__':
    main()

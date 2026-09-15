#!/usr/bin/env python3
"""
Graph analysis pipeline: MCMF, Louvain community detection, Yen's K-shortest paths.
Multi-format output: JSON, Graphviz DOT, SQLite.
"""

import json
import os
import heapq
import sqlite3
from collections import defaultdict, deque


# ======================== DATA LOADING ========================


def load_graph_from_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    metadata = {k: v for k, v in c.execute("SELECT key, value FROM metadata").fetchall()}
    edges = [
        {"from": r[0], "to": r[1], "capacity": r[2], "cost": r[3]}
        for r in c.execute(
            "SELECT from_node, to_node, capacity, cost FROM edges"
        ).fetchall()
    ]
    conn.close()
    return {
        "num_nodes": metadata["num_nodes"],
        "source": metadata["source"],
        "sink": metadata["sink"],
        "edges": edges,
    }


# ======================== MIN-COST MAX-FLOW ========================


class MinCostMaxFlow:
    """Successive shortest paths with SPFA (handles negative-cost residual edges)."""

    def __init__(self, n):
        self.n = n
        self.graph = [[] for _ in range(n)]
        self.edges = []

    def add_edge(self, u, v, cap, cost):
        self.graph[u].append(len(self.edges))
        self.edges.append([v, cap, cost, cap])
        self.graph[v].append(len(self.edges))
        self.edges.append([u, 0, -cost, 0])

    def solve(self, s, t):
        INF = float('inf')
        total_flow = 0
        total_cost = 0

        while True:
            dist = [INF] * self.n
            dist[s] = 0
            in_queue = [False] * self.n
            prev_edge = [-1] * self.n
            q = deque([s])
            in_queue[s] = True

            while q:
                u = q.popleft()
                in_queue[u] = False
                for eidx in self.graph[u]:
                    to, cap, cost, _ = self.edges[eidx]
                    if cap > 0 and dist[u] + cost < dist[to]:
                        dist[to] = dist[u] + cost
                        prev_edge[to] = eidx
                        if not in_queue[to]:
                            q.append(to)
                            in_queue[to] = True

            if dist[t] == INF:
                break

            bottleneck = INF
            v = t
            while v != s:
                eidx = prev_edge[v]
                bottleneck = min(bottleneck, self.edges[eidx][1])
                v = self.edges[eidx ^ 1][0]

            total_flow += bottleneck
            total_cost += bottleneck * dist[t]
            v = t
            while v != s:
                eidx = prev_edge[v]
                self.edges[eidx][1] -= bottleneck
                self.edges[eidx ^ 1][1] += bottleneck
                v = self.edges[eidx ^ 1][0]

        return total_flow, total_cost

    def get_edge_flows(self):
        result = []
        for i in range(0, len(self.edges), 2):
            flow = self.edges[i][3] - self.edges[i][1]
            if flow > 0:
                u = self.edges[i ^ 1][0]
                v = self.edges[i][0]
                result.append([u, v, flow])
        return result


# ======================== LOUVAIN COMMUNITY DETECTION ========================


def louvain_communities(num_nodes, directed_edges):
    """
    Louvain phase-1 (local moving) on undirected projection.
    directed_edges: list of (from, to, capacity)
    Returns: (assignment_dict, modularity, num_communities)
    """
    adj = defaultdict(lambda: defaultdict(float))
    for u, v, w in directed_edges:
        adj[u][v] += w
        adj[v][u] += w

    nodes = list(range(num_nodes))
    total_2m = sum(adj[u][v] for u in nodes for v in adj[u])
    if total_2m == 0:
        return {u: 0 for u in nodes}, 0.0, 1

    m = total_2m / 2.0
    k = {u: sum(adj[u].values()) for u in nodes}
    comm = {u: u for u in nodes}

    changed = True
    while changed:
        changed = False
        for node in nodes:
            cur_comm = comm[node]
            k_i = k[node]

            comm_link = defaultdict(float)
            for nb, w in adj[node].items():
                comm_link[comm[nb]] += w

            sigma_cur = sum(k[v] for v in nodes if comm[v] == cur_comm and v != node)
            k_i_in_cur = comm_link.get(cur_comm, 0.0)

            best_delta = 0.0
            best_comm = cur_comm

            for c, k_i_in_c in comm_link.items():
                if c == cur_comm:
                    continue
                sigma_c = sum(k[v] for v in nodes if comm[v] == c)
                delta = ((k_i_in_c - k_i_in_cur) / m
                         - k_i * (sigma_c - sigma_cur) / (2.0 * m * m))
                if delta > best_delta:
                    best_delta = delta
                    best_comm = c

            if best_comm != cur_comm:
                comm[node] = best_comm
                changed = True

    unique = sorted(set(comm.values()))
    remap = {c: i for i, c in enumerate(unique)}
    comm = {u: remap[comm[u]] for u in nodes}

    Q = 0.0
    for u in nodes:
        for v in adj[u]:
            if comm[u] == comm[v]:
                Q += adj[u][v] - k[u] * k[v] / total_2m
    Q /= total_2m

    return comm, Q, len(unique)


# ======================== YEN'S K-SHORTEST PATHS ========================


def _dijkstra(n, adj, src, dst, excl_nodes=None, excl_edges=None):
    if excl_nodes is None:
        excl_nodes = set()
    if excl_edges is None:
        excl_edges = set()

    INF = float('inf')
    dist = [INF] * n
    prev = [-1] * n
    dist[src] = 0
    pq = [(0, src)]
    done = [False] * n

    while pq:
        d, u = heapq.heappop(pq)
        if done[u]:
            continue
        if u in excl_nodes:
            continue
        done[u] = True
        if u == dst:
            break
        for v, c in adj.get(u, []):
            if v in excl_nodes or (u, v) in excl_edges:
                continue
            nd = d + c
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))

    if dist[dst] == INF:
        return INF, []

    path = []
    v = dst
    while v != -1:
        path.append(v)
        v = prev[v]
    return dist[dst], path[::-1]


def yens_k_shortest(n, edges, src, dst, k=5):
    adj = defaultdict(list)
    edge_cost = {}
    for u, v, c in edges:
        adj[u].append((v, c))
        edge_cost[(u, v)] = c

    def path_cost(path):
        return sum(edge_cost[(path[i], path[i + 1])] for i in range(len(path) - 1))

    c0, p0 = _dijkstra(n, adj, src, dst)
    if not p0:
        return []

    A = [(p0, c0)]
    B = []
    seen = {tuple(p0)}

    for _ in range(1, k):
        last_path = A[-1][0]
        for j in range(len(last_path) - 1):
            spur_node = last_path[j]
            root = last_path[:j + 1]

            excl_edges = set()
            for p, _ in A:
                if len(p) > j and p[:j + 1] == root:
                    excl_edges.add((p[j], p[j + 1]))

            excl_nodes = set(root[:-1])
            _, spur_path = _dijkstra(n, adj, spur_node, dst, excl_nodes, excl_edges)
            if spur_path:
                total_path = root[:-1] + spur_path
                tp = tuple(total_path)
                if tp not in seen:
                    tc = path_cost(total_path)
                    heapq.heappush(B, (tc, tp))
                    seen.add(tp)

        if not B:
            break

        bc, bp = heapq.heappop(B)
        A.append((list(bp), bc))

    return A


# ======================== DOT OUTPUT ========================

COMMUNITY_COLORS = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
    '#FFEAA7', '#DDA0DD', '#C9B1FF', '#FFB3BA',
    '#BAFFC9', '#BAE1FF',
]


def write_dot_file(filename, n, edge_flows, comm, cap_map):
    with open(filename, 'w') as f:
        f.write('digraph flow_network {\n')
        f.write('  rankdir=LR;\n')
        f.write('  node [style=filled];\n\n')

        for node_id in range(n):
            c_id = comm[node_id]
            color = COMMUNITY_COLORS[c_id % len(COMMUNITY_COLORS)]
            f.write(f'  {node_id} [label="{node_id}\\nC{c_id}" fillcolor="{color}"];\n')

        f.write('\n')

        for u, v, flow in edge_flows:
            cap = cap_map[(u, v)]
            f.write(f'  {u} -> {v} [label="{flow}/{cap}"];\n')

        f.write('}\n')


# ======================== ANALYSIS DB ========================


def write_analysis_db(filename, n, comm, paths, edge_flows, cap_map,
                      max_flow, min_cost, modularity, num_comm, cross_frac):
    if os.path.exists(filename):
        os.remove(filename)

    conn = sqlite3.connect(filename)
    c = conn.cursor()

    c.execute(
        'CREATE TABLE community_assignments '
        '(node_id INTEGER PRIMARY KEY, community_id INTEGER)'
    )
    for node_id in range(n):
        c.execute('INSERT INTO community_assignments VALUES (?, ?)',
                  (node_id, comm[node_id]))

    c.execute(
        'CREATE TABLE shortest_paths '
        '(rank INTEGER PRIMARY KEY, path TEXT, cost INTEGER)'
    )
    for i, (p, cost) in enumerate(paths):
        path_str = ','.join(str(x) for x in p)
        c.execute('INSERT INTO shortest_paths VALUES (?, ?, ?)',
                  (i + 1, path_str, cost))

    c.execute(
        'CREATE TABLE edge_flows '
        '(from_node INTEGER, to_node INTEGER, flow INTEGER, capacity INTEGER)'
    )
    for u, v, fl in edge_flows:
        c.execute('INSERT INTO edge_flows VALUES (?, ?, ?, ?)',
                  (u, v, fl, cap_map[(u, v)]))

    c.execute('CREATE TABLE metrics (key TEXT PRIMARY KEY, value REAL)')
    for key, val in [
        ('max_flow', float(max_flow)),
        ('min_cost', float(min_cost)),
        ('modularity', modularity),
        ('num_communities', float(num_comm)),
        ('cross_community_flow_fraction', cross_frac),
    ]:
        c.execute('INSERT INTO metrics VALUES (?, ?)', (key, val))

    conn.commit()
    conn.close()


# ======================== MAIN ========================


def main():
    net = load_graph_from_sqlite('/app/network.db')

    n = net['num_nodes']
    src = net['source']
    sink = net['sink']

    # Min-Cost Maximum Flow
    mcmf = MinCostMaxFlow(n)
    for e in net['edges']:
        mcmf.add_edge(e['from'], e['to'], e['capacity'], e['cost'])
    max_flow, min_cost = mcmf.solve(src, sink)
    edge_flows = mcmf.get_edge_flows()

    # Louvain Community Detection
    directed_edges = [(e['from'], e['to'], e['capacity']) for e in net['edges']]
    comm, modularity, num_comm = louvain_communities(n, directed_edges)

    # Yen's K-Shortest Paths
    cost_edges = [(e['from'], e['to'], e['cost']) for e in net['edges']]
    paths = yens_k_shortest(n, cost_edges, src, sink, k=5)

    # Cross-Community Flow Analysis
    total_edge_flow = sum(f for _, _, f in edge_flows)
    cross_flow = sum(f for u, v, f in edge_flows if comm[u] != comm[v])
    cross_frac = cross_flow / total_edge_flow if total_edge_flow > 0 else 0.0

    # Bottleneck Edge
    cap_map = {(e['from'], e['to']): e['capacity'] for e in net['edges']}
    best_bn = None
    best_bn_flow = -1
    for u, v, f in edge_flows:
        if comm[u] != comm[v] and f > best_bn_flow:
            best_bn_flow = f
            best_bn = {'from': u, 'to': v, 'flow': f, 'capacity': cap_map[(u, v)]}

    # Write results.json
    result = {
        'mcmf': {
            'max_flow': max_flow,
            'min_cost': min_cost,
            'edge_flows': edge_flows,
        },
        'communities': {
            'assignment': {str(u): c for u, c in comm.items()},
            'modularity': modularity,
            'num_communities': num_comm,
        },
        'shortest_paths': [{'path': p, 'cost': c} for p, c in paths],
        'cross_community_flow_fraction': cross_frac,
        'bottleneck_edge': best_bn,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(result, f, indent=2)

    # Write flow_graph.dot
    write_dot_file('/app/flow_graph.dot', n, edge_flows, comm, cap_map)

    # Write analysis.db
    write_analysis_db('/app/analysis.db', n, comm, paths, edge_flows, cap_map,
                      max_flow, min_cost, modularity, num_comm, cross_frac)

    print(f"Max flow: {max_flow}, Min cost: {min_cost}")
    print(f"Communities: {num_comm}, Modularity: {modularity:.4f}")
    print(f"Shortest paths: {len(paths)}")
    print(f"Cross-community flow fraction: {cross_frac:.4f}")
    print(f"Bottleneck: {best_bn}")


if __name__ == '__main__':
    main()

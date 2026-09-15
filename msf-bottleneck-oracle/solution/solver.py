#!/usr/bin/env python3

import sqlite3
import json
from collections import defaultdict, deque

# ===== READ CONFIG =====
with open('/app/network/config.json') as f:
    config = json.load(f)

threshold = None
for analysis in config['analyses']:
    if analysis['id'] == 'critical':
        threshold = analysis['threshold']
        break

output_file = config['output_file']
db_path = '/app/network/' + config['data_source']

# ===== READ DATABASE =====
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Active nodes
cur.execute("SELECT node_id, hostname FROM nodes WHERE status='active'")
active_nodes = dict(cur.fetchall())
active_set = set(active_nodes.keys())
hostname_to_id = {v: k for k, v in active_nodes.items()}

# Qualifying edges with weights from latest measurement
cur.execute("""
    SELECT e.edge_id, e.src_node, e.dst_node,
           m.latency_us + 100 * m.loss_permille + m.jitter_us AS weight
    FROM edges e
    JOIN measurements m ON m.edge_id = e.edge_id
    WHERE e.src_node != e.dst_node
      AND m.collected_at = (
          SELECT MAX(m2.collected_at)
          FROM measurements m2
          WHERE m2.edge_id = e.edge_id
      )
""")

all_graph_edges = []
for row in cur.fetchall():
    _, src, dst, w = row
    if src in active_set and dst in active_set:
        all_graph_edges.append((src, dst, w))

# Queries
cur.execute(
    "SELECT query_id, src_hostname, dst_hostname "
    "FROM analysis_queries ORDER BY query_id"
)
raw_queries = cur.fetchall()
conn.close()

# ===== UNION-FIND =====
N = len(active_set)
id_list = sorted(active_set)
id_to_idx = {nid: i for i, nid in enumerate(id_list)}

parent = list(range(N))
rank = [0] * N


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(x, y):
    rx, ry = find(x), find(y)
    if rx == ry:
        return False
    if rank[rx] < rank[ry]:
        rx, ry = ry, rx
    parent[ry] = rx
    if rank[rx] == rank[ry]:
        rank[rx] += 1
    return True


# ===== KRUSKAL'S MSF =====
sorted_edges = sorted(all_graph_edges, key=lambda e: e[2])
msf_edges = []
msf_edge_set = set()
msf_weight = 0

for src, dst, w in sorted_edges:
    si, di = id_to_idx[src], id_to_idx[dst]
    if union(si, di):
        msf_edges.append((src, dst, w))
        msf_edge_set.add((min(src, dst), max(src, dst)))
        msf_weight += w

# ===== COMPONENTS =====
comp_map = {}
comp_nodes = defaultdict(list)
for nid in active_set:
    root = find(id_to_idx[nid])
    comp_map[nid] = root
    comp_nodes[root].append(nid)

num_components = len(comp_nodes)
component_sizes = sorted(len(c) for c in comp_nodes.values())

# ===== MSF ADJACENCY =====
msf_adj = defaultdict(list)
for src, dst, w in msf_edges:
    msf_adj[src].append((dst, w))
    msf_adj[dst].append((src, w))


# ===== BOTTLENECK BFS =====
def bottleneck_bfs(u, v):
    if comp_map.get(u) != comp_map.get(v):
        return -1
    if u == v:
        return 0
    visited = {u}
    queue = deque([(u, 0)])
    while queue:
        node, mx = queue.popleft()
        for nbr, w in msf_adj[node]:
            if nbr not in visited:
                visited.add(nbr)
                nm = max(mx, w)
                if nbr == v:
                    return nm
                queue.append((nbr, nm))
    return -1


# ===== BOTTLENECK ANSWERS =====
bottleneck_answers = []
for qid, src_h, dst_h in raw_queries:
    src_id = hostname_to_id.get(src_h)
    dst_id = hostname_to_id.get(dst_h)
    if src_id is None or dst_id is None:
        bottleneck_answers.append(-1)
    else:
        bottleneck_answers.append(bottleneck_bfs(src_id, dst_id))


# ===== CRITICAL EDGE ANALYSIS =====
def bfs_subtree(start, skip_u, skip_v):
    """BFS from start on MSF, skipping the edge (skip_u, skip_v)."""
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nbr, w in msf_adj[node]:
            if nbr not in visited:
                if ((node == skip_u and nbr == skip_v) or
                        (node == skip_v and nbr == skip_u)):
                    continue
                visited.add(nbr)
                queue.append(nbr)
    return visited


critical_edges = []
for src, dst, w_e in msf_edges:
    comp_u = bfs_subtree(src, src, dst)

    # Find best replacement non-MSF edge crossing the cut
    best_replacement = float('inf')
    for s, d, ew in all_graph_edges:
        key = (min(s, d), max(s, d))
        if key in msf_edge_set:
            continue
        if (s in comp_u) != (d in comp_u):
            best_replacement = min(best_replacement, ew)

    if best_replacement == float('inf') or best_replacement - w_e > threshold:
        hn = sorted([active_nodes[src], active_nodes[dst]])
        critical_edges.append([hn[0], hn[1], w_e])

critical_edges.sort(key=lambda x: x[2])

# ===== SECOND-BEST MSF =====
min_swap = float('inf')
for s, d, ew in all_graph_edges:
    key = (min(s, d), max(s, d))
    if key in msf_edge_set:
        continue
    bn = bottleneck_bfs(s, d)
    if bn < 0:
        continue
    min_swap = min(min_swap, ew - bn)

second_best = -1 if min_swap == float('inf') else msf_weight + min_swap

# ===== WRITE RESULTS =====
results = {
    "active_node_count": len(active_set),
    "edge_count": len(all_graph_edges),
    "num_components": num_components,
    "component_sizes": component_sizes,
    "msf_total_weight": msf_weight,
    "bottleneck_answers": bottleneck_answers,
    "critical_edges": critical_edges,
    "second_best_msf_weight": second_best,
}

with open(output_file, 'w') as f:
    json.dump(results, f, indent=2)

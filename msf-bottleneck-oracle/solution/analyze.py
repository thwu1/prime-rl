#!/usr/bin/env python3

"""
Analysis stage for the network topology pipeline.
Reads intermediate JSON files produced by the extract/transform stages,
performs graph analysis, and outputs results.json and msf.dot.
"""

import json
import os
from collections import defaultdict, deque

# ===== READ PIPELINE INTERMEDIATE DATA =====
with open('/app/pipeline/build/nodes.json') as f:
    raw_nodes = json.load(f)

with open('/app/pipeline/build/weighted_edges.json') as f:
    raw_edges = json.load(f)

with open('/app/pipeline/build/queries.json') as f:
    raw_queries = json.load(f)

with open('/app/network/config.json') as f:
    config = json.load(f)

# ===== BUILD NODE MAPPINGS =====
active_nodes = {n['node_id']: n['hostname'] for n in raw_nodes}
active_set = set(active_nodes.keys())
hostname_to_id = {n['hostname']: n['node_id'] for n in raw_nodes}
site_map = {n['node_id']: n['site'] for n in raw_nodes}

# ===== FILTER EDGES TO ACTIVE-NODE PAIRS =====
all_graph_edges = []
for e in raw_edges:
    src, dst, w = e['src_node'], e['dst_node'], e['weight']
    if src in active_set and dst in active_set:
        all_graph_edges.append((src, dst, w))

# ===== GET ANALYSIS PARAMETERS =====
threshold = None
for analysis in config['analyses']:
    if analysis['id'] == 'critical':
        threshold = analysis['threshold']
        break

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
for q in raw_queries:
    src_h = q['src_hostname']
    dst_h = q['dst_hostname']
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

with open(config['output_file'], 'w') as f:
    json.dump(results, f, indent=2)

# ===== GENERATE DOT FILE FOR MSF VISUALIZATION =====
vis_config = config.get('visualization', {})
site_colors = vis_config.get('site_colors', {})
graph_title = vis_config.get('graph_title', 'MSF')

dot_lines = ['graph MSF {']
dot_lines.append('  graph [label="{}" fontsize=16 labelloc=t];'.format(graph_title))
dot_lines.append('  node [shape=ellipse style=filled fontsize=8];')

# Group nodes by site for colored subgraphs
# Use numeric DOT identifiers with explicit label attributes to avoid
# encoding issues with hyphens in hostnames when rendering to SVG.
sites = defaultdict(list)
for nid in active_set:
    sites[site_map[nid]].append(nid)

for site_name in sorted(sites.keys()):
    color = site_colors.get(site_name, '#cccccc')
    dot_lines.append('  subgraph cluster_{} {{'.format(site_name))
    dot_lines.append('    label="{}";'.format(site_name))
    dot_lines.append('    node [fillcolor="{}"];'.format(color))
    for nid in sorted(sites[site_name]):
        hostname = active_nodes[nid]
        dot_lines.append('    n{} [label="{}"];'.format(nid, hostname))
    dot_lines.append('  }')

# MSF edges with weight labels
for src, dst, w in msf_edges:
    dot_lines.append('  n{} -- n{} [label="{}" penwidth=1.5];'.format(src, dst, w))

dot_lines.append('}')

dot_path = vis_config.get('output_dot', '/app/pipeline/build/msf.dot')
os.makedirs(os.path.dirname(dot_path), exist_ok=True)
with open(dot_path, 'w') as f:
    f.write('\n'.join(dot_lines) + '\n')

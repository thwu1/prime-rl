#!/usr/bin/env python3

"""
Solve the graph pipeline analysis task:
1. Extract edges from SQLite (label-based), Matrix Market, GraphML, gzipped edge list
2. Merge and deduplicate
3. Compute structural metrics using igraph and manual algorithms
"""

import json
import os
import gzip
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
import igraph as ig


# =====================================================================
# Data extraction
# =====================================================================

def extract_sqlite_edges(db_path):
    """Extract edges from SQLite, resolving label->ID via JOIN."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Build label->id mapping
    c.execute('SELECT sensor_id, label FROM sensors')
    label_to_id = {label: sid for sid, label in c.fetchall()}
    # Extract edges, converting labels to numeric IDs
    c.execute('SELECT source_label, target_label FROM connections')
    edges = set()
    for src_label, tgt_label in c.fetchall():
        if src_label in label_to_id and tgt_label in label_to_id:
            u = label_to_id[src_label]
            v = label_to_id[tgt_label]
            if u != v:
                edges.add((min(u, v), max(u, v)))
    conn.close()
    return edges


def extract_mtx_edges(path):
    """Parse Matrix Market coordinate pattern symmetric format."""
    edges = set()
    header_done = False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('%'):
                continue
            if not header_done:
                header_done = True  # skip size line
                continue
            parts = line.split()
            if len(parts) >= 2:
                u, v = int(parts[0]), int(parts[1])
                if u != v:
                    edges.add((min(u, v), max(u, v)))
    return edges


def extract_graphml_edges(path):
    """Parse GraphML XML, handling namespace."""
    tree = ET.parse(path)
    root = tree.getroot()
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'
    edges = set()
    for edge in root.iter(f'{ns}edge'):
        src = edge.get('source')
        tgt = edge.get('target')
        u = int(src.lstrip('v'))
        v = int(tgt.lstrip('v'))
        if u != v:
            edges.add((min(u, v), max(u, v)))
    return edges


def extract_gz_edges(path):
    """Parse gzipped edge list, detecting 0-based indexing from comments."""
    raw_edges = []
    zero_based = False
    with gzip.open(path, 'rt') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if '0-bas' in line.lower() or '0-index' in line.lower():
                    zero_based = True
                continue
            parts = line.split()
            if len(parts) >= 2:
                raw_edges.append((int(parts[0]), int(parts[1])))
    # Also detect by min ID as fallback
    if not zero_based and raw_edges:
        min_id = min(min(u, v) for u, v in raw_edges)
        if min_id == 0:
            zero_based = True
    if zero_based:
        raw_edges = [(u + 1, v + 1) for u, v in raw_edges]
    edges = set()
    for u, v in raw_edges:
        if u != v:
            edges.add((min(u, v), max(u, v)))
    return edges


def discover_and_load(base_dir):
    """Discover all data files and extract edges."""
    all_edges = set()
    for root_dir, dirs, files in os.walk(base_dir):
        for fname in files:
            path = os.path.join(root_dir, fname)
            if fname.endswith('.db'):
                all_edges |= extract_sqlite_edges(path)
            elif fname.endswith('.mtx'):
                all_edges |= extract_mtx_edges(path)
            elif fname.endswith('.graphml'):
                all_edges |= extract_graphml_edges(path)
            elif fname.endswith('.gz'):
                all_edges |= extract_gz_edges(path)
    return all_edges


# =====================================================================
# Manual graph algorithms (for k-truss, triangles)
# =====================================================================

def build_adj(edges):
    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    return adj


def count_triangles(edges):
    adj = build_adj(edges)
    total = 0
    for u, v in edges:
        total += len(adj[u] & adj[v])
    return total // 3


def compute_ktruss(edge_set, k):
    remaining = set(edge_set)
    while True:
        adj = build_adj(remaining)
        drop = set()
        for u, v in remaining:
            if len(adj[u] & adj[v]) < k - 2:
                drop.add((u, v))
        if not drop:
            break
        remaining -= drop
    return remaining


def truss_decomposition(edges):
    trussness = {}
    prev = set(edges)
    k = 3
    while prev:
        cur = compute_ktruss(prev, k)
        for e in prev - cur:
            trussness[e] = k - 1
        prev = cur
        k += 1
    return trussness


def count_components(edges):
    if not edges:
        return 0
    adj = build_adj(edges)
    nodes = set()
    for u, v in edges:
        nodes.update([u, v])
    visited = set()
    num = 0
    for n in nodes:
        if n in visited:
            continue
        num += 1
        stack = [n]
        while stack:
            x = stack.pop()
            if x in visited:
                continue
            visited.add(x)
            stack.extend(adj[x] - visited)
    return num


# =====================================================================
# Main
# =====================================================================

def main():
    # Step 1: Load and merge data
    all_edges = discover_and_load('/opt/graphdata')
    nodes = set()
    for u, v in all_edges:
        nodes.update([u, v])

    # Step 2: Build igraph graph (0-indexed)
    max_node = max(nodes)
    g = ig.Graph(n=max_node, directed=False)
    for u, v in all_edges:
        g.add_edge(u - 1, v - 1)

    # Step 3: Compute metrics

    # Basic
    num_nodes = len(nodes)
    num_edges = len(all_edges)
    tri_count = count_triangles(all_edges)

    # K-truss decomposition (manual — igraph may not have truss())
    tn = truss_decomposition(all_edges)
    max_trussness = max(tn.values()) if tn else 0
    trussness_hist = defaultdict(int)
    for v in tn.values():
        trussness_hist[v] += 1

    # K-truss connected components
    ktruss_comps = {}
    for k in range(2, max_trussness + 1):
        kt = compute_ktruss(all_edges, k)
        if kt:
            ktruss_comps[str(k)] = count_components(kt)

    # K-core decomposition via igraph
    coreness_list = g.coreness()
    coreness = {}
    for i in range(max_node):
        if (i + 1) in nodes:
            coreness[i + 1] = coreness_list[i]
    degeneracy = max(coreness.values())
    core_hist = defaultdict(int)
    for c in coreness.values():
        core_hist[c] += 1

    # Cliques via igraph
    clique_number = g.clique_number()
    maximal_cliques = g.maximal_cliques(min=3)
    num_maximal_cliques = len(maximal_cliques)

    # Diameter via igraph
    diameter = g.diameter()

    # Articulation points via igraph
    art_points = g.articulation_points()
    num_articulation_points = len(art_points)

    # Bridges via igraph
    bridge_list = g.bridges()
    num_bridges = len(bridge_list)

    # Connected components via igraph
    components = g.connected_components()
    num_connected_components = len(components)

    # Densest subgraph (nodes in max-trussness edges)
    densest = set()
    for e, kv in tn.items():
        if kv == max_trussness:
            densest.add(e[0])
            densest.add(e[1])

    results = {
        "num_nodes": num_nodes,
        "num_edges": num_edges,
        "triangle_count": tri_count,
        "max_trussness": max_trussness,
        "trussness_histogram": {str(k): v for k, v in sorted(trussness_hist.items())},
        "degeneracy": degeneracy,
        "core_histogram": {str(k): v for k, v in sorted(core_hist.items())},
        "clique_number": clique_number,
        "num_maximal_cliques": num_maximal_cliques,
        "diameter": diameter,
        "num_articulation_points": num_articulation_points,
        "num_bridges": num_bridges,
        "num_connected_components": num_connected_components,
        "ktruss_components": ktruss_comps,
        "densest_subgraph_nodes": sorted(densest),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()

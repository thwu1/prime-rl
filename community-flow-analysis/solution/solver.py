#!/usr/bin/env python3
"""
"""
import sqlite3
import json
import networkx as nx
from networkx.algorithms.community import louvain_communities


def main():
    conn = sqlite3.connect('/app/network.db')
    conn.row_factory = sqlite3.Row

    # Discover node status
    active = set()
    inactive = set()
    for row in conn.execute("SELECT id, status FROM nodes"):
        (active if row['status'] == 'active' else inactive).add(row['id'])

    # Clean links
    good = []
    bad = 0
    for row in conn.execute("SELECT node_a, node_b, capacity, status FROM links"):
        a, b, cap, st = row['node_a'], row['node_b'], row['capacity'], row['status']
        if a == b or cap <= 0 or st != 'up' or a not in active or b not in active:
            bad += 1
            continue
        good.append((a, b, cap))
    conn.close()

    issues = len(inactive) + bad

    # Build graph
    G = nx.Graph()
    G.add_nodes_from(active)
    for a, b, cap in good:
        if G.has_edge(a, b):
            G[a][b]['capacity'] += cap
        else:
            G.add_edge(a, b, capacity=cap)

    # Community detection
    comms = louvain_communities(G, weight='capacity', seed=42, resolution=1.0)
    comms = sorted([sorted(c) for c in comms], key=lambda x: x[0])
    cmap = {}
    for idx, c in enumerate(comms):
        for n in c:
            cmap[str(n)] = idx

    mod = nx.community.modularity(G, [set(c) for c in comms], weight='capacity')

    # Max flow
    src, tgt = 1, 29
    base_flow = nx.maximum_flow_value(G, src, tgt, capacity='capacity')

    # Critical link (brute-force all edges)
    best_impact = 0
    best_edge = (None, None)
    for u, v in list(G.edges()):
        cap = G[u][v]['capacity']
        G.remove_edge(u, v)
        if nx.has_path(G, src, tgt):
            f = nx.maximum_flow_value(G, src, tgt, capacity='capacity')
        else:
            f = 0
        impact = base_flow - f
        if impact > best_impact:
            best_impact = impact
            best_edge = (u, v)
        G.add_edge(u, v, capacity=cap)

    # Bridges
    bridges = [[u, v] for u, v in nx.bridges(G)]

    results = {
        "active_nodes": len(active),
        "valid_links": len(good),
        "data_issues_found": issues,
        "community_count": len(comms),
        "modularity": round(mod, 6),
        "community_map": cmap,
        "max_flow": {
            "source": src,
            "target": tgt,
            "value": int(base_flow) if base_flow == int(base_flow) else base_flow,
        },
        "critical_link": {
            "node_a": best_edge[0],
            "node_b": best_edge[1],
            "flow_impact": int(best_impact) if best_impact == int(best_impact) else best_impact,
        },
        "bridges": bridges,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Network topology models and route computation.

Implements Dijkstra's shortest-path algorithm for computing optimal routes
between nodes in the network topology. For equal-cost paths, the
alphabetically first next-hop node is preferred to ensure deterministic
route selection.
"""

import json
import heapq
import sqlite3


def load_topology(path='/app/config/topology.json'):
    """Load network topology from JSON file."""
    with open(path) as f:
        return json.load(f)


def compute_routes(topology):
    """
    Compute shortest-path routes for all node pairs using Dijkstra's algorithm.

    For equal-cost paths, the alphabetically first next-hop node is preferred
    to ensure deterministic route selection.

    Returns list of route dicts with keys:
        source_node, destination_network, next_hop_node, metric, status
    """
    nodes = {n['name']: n for n in topology['nodes']}
    node_names = sorted(nodes.keys())

    # Build adjacency list
    adj = {name: [] for name in node_names}
    for link in topology['links']:
        adj[link['node_a']].append((link['node_b'], link['cost']))
        adj[link['node_b']].append((link['node_a'], link['cost']))

    routes = []

    for source in node_names:
        # Dijkstra from source
        dist = {n: float('inf') for n in node_names}
        next_hop = {n: None for n in node_names}
        dist[source] = 0
        visited = set()
        pq = [(0, source)]

        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)

            for v, cost in sorted(adj[u], key=lambda x: x[0]):
                new_dist = d + cost
                if new_dist < dist[v]:
                    dist[v] = new_dist
                    if u == source:
                        next_hop[v] = v
                    else:
                        next_hop[v] = next_hop[u]
                    heapq.heappush(pq, (new_dist, v))

        for dest in node_names:
            if dest == source:
                continue
            if dist[dest] < float('inf'):
                routes.append({
                    'source_node': source,
                    'destination_network': nodes[dest]['subnet'],
                    'next_hop_node': next_hop[dest],
                    'metric': dist[dest],
                    'status': 'active'
                })

    return routes


def init_db(db_path='/app/db/network.db'):
    """Initialize the database schema."""
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS nodes (
        name TEXT PRIMARY KEY,
        subnet TEXT NOT NULL,
        role TEXT NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node_a TEXT NOT NULL,
        node_b TEXT NOT NULL,
        cost INTEGER NOT NULL,
        FOREIGN KEY (node_a) REFERENCES nodes(name),
        FOREIGN KEY (node_b) REFERENCES nodes(name)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_node TEXT NOT NULL,
        destination_network TEXT NOT NULL,
        next_hop_node TEXT NOT NULL,
        metric INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source_node, destination_network)
    )''')
    conn.commit()
    return conn


def insert_routes(db_path, routes):
    """Insert routes into the database."""
    conn = sqlite3.connect(db_path)
    for route in routes:
        conn.execute(
            'INSERT OR REPLACE INTO routes '
            '(source_node, destination_network, next_hop_node, metric, status) '
            'VALUES (?, ?, ?, ?, ?)',
            (route['source_node'], route['destination_network'],
             route['next_hop_node'], route['metric'],
             route.get('status', 'active'))
        )
    conn.commit()
    conn.close()


if __name__ == '__main__':
    topology = load_topology()
    routes = compute_routes(topology)
    print(f"Computed {len(routes)} routes from topology:")
    for r in sorted(routes, key=lambda x: (x['source_node'], x['destination_network'])):
        print(f"  {r['source_node']:15s} -> {r['destination_network']:15s} "
              f"via {r['next_hop_node']:15s} (metric {r['metric']})")

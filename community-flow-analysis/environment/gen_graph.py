#!/usr/bin/env python3
"""Generate graph.json: 4 K5 cliques with weighted bridge edges."""
import json

nodes = list(range(20))
edges = []

# K5 cliques: {0-4}, {5-9}, {10-14}, {15-19}, weight=10 each pair
for base in [0, 5, 10, 15]:
    for i in range(base, base + 5):
        for j in range(i + 1, base + 5):
            edges.append({"source": i, "target": j, "weight": 10})

# Bridge edges between cliques
for s, t, w in [(4,5,3),(3,6,2),(9,10,4),(8,11,1),(14,15,3),(13,16,2),(4,10,1),(9,15,2)]:
    edges.append({"source": s, "target": t, "weight": w})

with open("/app/graph.json", "w") as f:
    json.dump({"nodes": nodes, "edges": edges, "source_node": 0, "target_node": 19}, f, indent=2)

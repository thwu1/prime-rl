#!/usr/bin/env python3
"""Generate test graphs for the graph centrality engine task."""
import os
import random

DATA = "/app/data"
os.makedirs(DATA, exist_ok=True)


def write_graph(path, n, edges):
    with open(path, "w") as f:
        f.write(f"{n} {len(edges)}\n")
        for u, v in edges:
            f.write(f"{u} {v}\n")


# --- Graph 1: small directed graph (7 vertices, 11 edges) ---
write_graph(
    os.path.join(DATA, "small.txt"), 7,
    [(0,1),(0,2),(0,6),(1,3),(1,4),(2,3),(2,4),(3,5),(3,6),(4,5),(5,6)],
)

# --- Graph 2: directed path (12 vertices) ---
n = 12
write_graph(
    os.path.join(DATA, "path.txt"), n,
    [(i, i + 1) for i in range(n - 1)],
)

# --- Graph 3: directed cycle (8 vertices) ---
n = 8
write_graph(
    os.path.join(DATA, "cycle.txt"), n,
    [(i, (i + 1) % n) for i in range(n)],
)

# --- Graph 4: disconnected graph (10 vertices) ---
# Component 1: 4-cycle {0,1,2,3}
# Component 2: 4-cycle {5,6,7,8} plus extra edge 5->7
# Isolated: {4, 9}   (dangling nodes for PageRank)
write_graph(
    os.path.join(DATA, "disconnected.txt"), 10,
    [(0,1),(1,2),(2,3),(3,0),(5,6),(6,7),(7,8),(8,5),(5,7)],
)

# --- Graph 5: random directed graph (300 vertices, seeded) ---
random.seed(418)
n = 300
edge_set = set()
# spanning tree so most vertices are reachable from vertex 0
perm = list(range(n))
random.shuffle(perm)
for i in range(1, n):
    parent = random.randint(0, i - 1)
    edge_set.add((perm[parent], perm[i]))
# additional random edges (including possible self-loops)
for _ in range(2700):
    u = random.randint(0, n - 1)
    v = random.randint(0, n - 1)
    edge_set.add((u, v))
edges = sorted(edge_set)
write_graph(os.path.join(DATA, "random.txt"), n, edges)

print(f"Generated 5 graphs in {DATA}/")

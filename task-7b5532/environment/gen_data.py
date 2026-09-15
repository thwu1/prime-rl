#!/usr/bin/env python3
"""Generate deterministic test data for the DataFrog engine task."""
import random
import os

os.makedirs('/app/data', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)
os.makedirs('/app/src/bin', exist_ok=True)

# Graph for TC and triangles: 50 nodes, 200 random directed edges
random.seed(42)
N = 50
edges = set()
while len(edges) < 200:
    a = random.randint(0, N - 1)
    b = random.randint(0, N - 1)
    if a != b:
        edges.add((a, b))

with open('/app/data/edges.txt', 'w') as f:
    for a, b in sorted(edges):
        f.write(f'{a} {b}\n')

# CFG for reaching defs: 30-node control flow graph
cfg = set()
for i in range(29):
    cfg.add((i, i + 1))
cfg.add((5, 15))
cfg.add((10, 20))
cfg.add((15, 25))
cfg.add((20, 5))
cfg.add((25, 10))
cfg.add((29, 0))

with open('/app/data/cfg.txt', 'w') as f:
    for a, b in sorted(cfg):
        f.write(f'{a} {b}\n')

# Gen set: definitions generated at specific nodes (10 defs)
random.seed(123)
gen = set()
for d in range(10):
    for _ in range(random.randint(1, 3)):
        node = random.randint(0, 29)
        gen.add((node, d))

with open('/app/data/gen.txt', 'w') as f:
    for node, d in sorted(gen):
        f.write(f'{node} {d}\n')

# Kill set: definitions killed at specific nodes
random.seed(456)
kill = set()
for d in range(10):
    for _ in range(random.randint(1, 4)):
        node = random.randint(0, 29)
        if (node, d) not in gen:
            kill.add((node, d))

with open('/app/data/kill.txt', 'w') as f:
    for node, d in sorted(kill):
        f.write(f'{node} {d}\n')

# Block nodes: nodes that block all definition propagation
block_nodes = [7, 18, 23]
with open('/app/data/block.txt', 'w') as f:
    for n in sorted(block_nodes):
        f.write(f'{n}\n')

print("Data generation complete.")

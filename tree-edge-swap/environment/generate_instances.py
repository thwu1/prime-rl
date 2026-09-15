#!/usr/bin/env python3
"""Generate tree instances for the edge-swap diameter optimization task."""
import random
import os

os.makedirs('/app/instances', exist_ok=True)


def write_instance(path, n, edges):
    assert len(edges) == n - 1, f"Expected {n-1} edges, got {len(edges)}"
    with open(path, 'w') as f:
        f.write(f"{n}\n")
        for u, v in edges:
            f.write(f"{u} {v}\n")


# Instance 1: COCI sample (N=7) - known answer is 3
write_instance('/app/instances/instance_01.txt', 7, [
    (1, 3), (2, 3), (2, 7), (4, 3), (7, 5), (3, 6)
])

# Instance 2: Small random tree (N=25, seed=42)
random.seed(42)
n = 25
edges = [(random.randint(1, i - 1), i) for i in range(2, n + 1)]
write_instance('/app/instances/instance_02.txt', n, edges)

# Instance 3: Path graph (N=500) - tests diameter bisection logic
n = 500
edges = [(i, i + 1) for i in range(1, n)]
write_instance('/app/instances/instance_03.txt', n, edges)

# Instance 4: Binary-ish tree (N=5000, seed=100)
random.seed(100)
n = 5000
edges = []
for i in range(2, n + 1):
    if i <= 3:
        p = 1
    else:
        p = random.randint(max(1, i // 2 - 50), i - 1)
    edges.append((p, i))
write_instance('/app/instances/instance_04.txt', n, edges)

# Instance 5: Large random tree (N=80000, seed=456)
random.seed(456)
n = 80000
edges = []
for i in range(2, n + 1):
    if random.random() < 0.2:
        p = random.randint(max(1, i - 5), i - 1)
    else:
        p = random.randint(1, i - 1)
    edges.append((p, i))
write_instance('/app/instances/instance_05.txt', n, edges)

# Instance 6: Large caterpillar (N=150000, seed=789)
random.seed(789)
n = 150000
spine_len = n // 3  # 50000 nodes in spine
edges = [(i, i + 1) for i in range(1, spine_len)]  # 49999 spine edges
node = spine_len + 1
while node <= n:
    spine_node = random.randint(1, spine_len)
    edges.append((spine_node, node))
    node += 1
# Total edges: (spine_len - 1) + (n - spine_len) = n - 1
write_instance('/app/instances/instance_06.txt', n, edges)

print("All instances generated.")

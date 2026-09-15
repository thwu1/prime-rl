#!/usr/bin/env python3
"""

Generate deterministic graph data for incremental triangle counting
and truss decomposition task.
"""
import random
import os


def main():
    random.seed(20240315)

    N = 5000
    NUM_COMMUNITIES = 10
    COMMUNITY_SIZE = 500
    INTRA_PROB = 0.02
    NUM_HUBS = 20
    HUB_CONNECTIONS = 100
    NUM_INTER = 2000
    NUM_BATCHES = 300
    OPS_PER_BATCH = 30
    DELETE_PROB = 0.45

    edges = set()

    # Community structure: dense intra-community edges create many triangles
    for c in range(NUM_COMMUNITIES):
        base = c * COMMUNITY_SIZE
        for i in range(base, base + COMMUNITY_SIZE):
            for j in range(i + 1, base + COMMUNITY_SIZE):
                if random.random() < INTRA_PROB:
                    edges.add((i, j))

    # Hub nodes: high-degree nodes connecting across communities
    hubs = random.sample(range(N), NUM_HUBS)
    for hub in hubs:
        targets = random.sample(range(N), HUB_CONNECTIONS)
        for t in targets:
            if t != hub:
                edges.add((min(hub, t), max(hub, t)))

    # Inter-community edges
    for _ in range(NUM_INTER):
        u = random.randint(0, N - 1)
        v = random.randint(0, N - 1)
        if u != v:
            edges.add((min(u, v), max(u, v)))

    # Write initial edges to /data/ (outside /app/ to survive volume mounts)
    os.makedirs('/data', exist_ok=True)
    initial_edges = sorted(edges)

    with open('/data/initial_edges.csv', 'w') as f:
        f.write('u,v\n')
        for u, v in initial_edges:
            f.write(f'{u},{v}\n')

    # Generate operations using list+set for deterministic random deletion
    edge_list = list(initial_edges)
    edge_set = set(initial_edges)
    all_ops = []

    for batch_id in range(NUM_BATCHES):
        batch_ops = []
        for _ in range(OPS_PER_BATCH):
            if random.random() < DELETE_PROB and len(edge_list) > 1000:
                idx = random.randint(0, len(edge_list) - 1)
                edge = edge_list[idx]
                # Swap with last and pop for O(1) removal
                edge_list[idx] = edge_list[-1]
                edge_list.pop()
                edge_set.discard(edge)
                batch_ops.append((batch_id, '-', edge[0], edge[1]))
            else:
                for _ in range(500):
                    u = random.randint(0, N - 1)
                    v = random.randint(0, N - 1)
                    if u != v:
                        u, v = min(u, v), max(u, v)
                        if (u, v) not in edge_set:
                            edge_set.add((u, v))
                            edge_list.append((u, v))
                            batch_ops.append((batch_id, '+', u, v))
                            break
        all_ops.extend(batch_ops)

    with open('/data/operations.csv', 'w') as f:
        f.write('batch_id,op,u,v\n')
        for bid, op, u, v in all_ops:
            f.write(f'{bid},{op},{u},{v}\n')

    print(f"Generated: {N} nodes, {len(initial_edges)} initial edges, "
          f"{len(all_ops)} operations across {NUM_BATCHES} batches")


if __name__ == '__main__':
    main()

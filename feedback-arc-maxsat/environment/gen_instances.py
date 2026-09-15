"""Generate weighted directed graph instances for minimum feedback arc set."""
import random
import os

os.makedirs('/app/instances', exist_ok=True)


def generate_graph(n, fwd_density, bwd_fraction, seed, filepath):
    """Generate a random weighted directed graph with guaranteed cycles.

    Forward edges go from lower to higher vertex indices.
    Backward edges create cycles by going from higher to lower indices.
    """
    random.seed(seed)
    edge_dict = {}

    # Forward edges: i -> j where i < j
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            if random.random() < fwd_density:
                edge_dict[(i, j)] = random.randint(1, 10)

    # Backward edges: i -> j where i > j (creates cycles)
    n_fwd = len(edge_dict)
    n_bwd = max(3, int(n_fwd * bwd_fraction))
    added = 0
    attempts = 0
    while added < n_bwd and attempts < n_bwd * 50:
        attempts += 1
        i = random.randint(2, n)
        j = random.randint(1, i - 1)
        if (i, j) not in edge_dict:
            edge_dict[(i, j)] = random.randint(1, 10)
            added += 1

    edges = sorted(edge_dict.items())
    with open(filepath, 'w') as f:
        f.write('{} {}\n'.format(n, len(edges)))
        for (u, v), w in edges:
            f.write('{} {} {}\n'.format(u, v, w))


generate_graph(6,  0.60, 0.50, 42,    '/app/instances/graph_01.txt')
generate_graph(10, 0.40, 0.45, 137,   '/app/instances/graph_02.txt')
generate_graph(16, 0.30, 0.40, 2718,  '/app/instances/graph_03.txt')
generate_graph(24, 0.20, 0.35, 31415, '/app/instances/graph_04.txt')

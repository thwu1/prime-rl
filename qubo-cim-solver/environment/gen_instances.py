#!/usr/bin/env python3
"""Generate optimization problem instances."""
import json
import os


def gen_ising_chain():
    """8-spin anti-ferromagnetic chain with external field.

    Ground state: [-1,+1,-1,+1,-1,+1,-1,+1], energy = -7.8
    The field h[0]=0.5 biases spin 0 toward -1 and h[7]=-0.3 biases spin 7 toward +1,
    breaking degeneracy of the two alternating AF patterns.
    """
    return {
        "type": "ising",
        "n": 8,
        "couplings": [
            [0, 1, 1.0], [1, 2, 1.0], [2, 3, 1.0], [3, 4, 1.0],
            [4, 5, 1.0], [5, 6, 1.0], [6, 7, 1.0]
        ],
        "fields": [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.3]
    }


def gen_ising_frustrated():
    """12-spin frustrated triangulated grid (3 rows x 4 columns).

    All anti-ferromagnetic couplings on a grid augmented with diagonal edges,
    creating triangular plaquettes that are geometrically frustrated.
    Layout:
       0  1  2  3
       4  5  6  7
       8  9 10 11
    """
    couplings = []
    # Horizontal edges (9)
    for row in range(3):
        for col in range(3):
            i = row * 4 + col
            j = row * 4 + col + 1
            couplings.append([i, j, 1.0])
    # Vertical edges (8)
    for row in range(2):
        for col in range(4):
            i = row * 4 + col
            j = (row + 1) * 4 + col
            couplings.append([i, j, 1.0])
    # Diagonal edges down-right (6), creating frustrated triangles
    for row in range(2):
        for col in range(3):
            i = row * 4 + col
            j = (row + 1) * 4 + col + 1
            couplings.append([i, j, 1.0])
    return {
        "type": "ising",
        "n": 12,
        "couplings": couplings,
        "fields": [0.0] * 12
    }


def gen_ising_sk20():
    """20-spin Sherrington-Kirkpatrick model with deterministic couplings.

    Fully connected with J_ij = ((i*17 + j*31 + 7) % 101) / 50 - 1.
    Couplings range in [-1.0, 1.0] with both FM and AFM interactions.
    """
    n = 20
    couplings = []
    for i in range(n):
        for j in range(i + 1, n):
            val = ((i * 17 + j * 31 + 7) % 101) / 50.0 - 1.0
            couplings.append([i, j, round(val, 4)])
    return {
        "type": "ising",
        "n": n,
        "couplings": couplings,
        "fields": [0.0] * n
    }


def gen_qubo_maxcut():
    """Max-Cut on the Petersen graph as QUBO.

    10 vertices, 15 edges, 3-regular. Max cut = 12 (attained by any
    maximum independent set of size 4). Ground QUBO energy = -12.

    QUBO formulation: Q_ii = -deg(i), Q_ij = 2 for edges (i<j).
    """
    n = 10
    edges = [
        (0, 1), (0, 4), (0, 5),
        (1, 2), (1, 6),
        (2, 3), (2, 7),
        (3, 4), (3, 8),
        (4, 9),
        (5, 7), (5, 8),
        (6, 8), (6, 9),
        (7, 9)
    ]
    Q = [[0] * n for _ in range(n)]
    for i in range(n):
        Q[i][i] = -3
    for i, j in edges:
        Q[i][j] = 2
    return {
        "type": "qubo",
        "n": n,
        "Q": Q
    }


if __name__ == "__main__":
    os.makedirs("/app/instances", exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)
    instances = {
        "ising_chain": gen_ising_chain(),
        "ising_frustrated": gen_ising_frustrated(),
        "ising_sk20": gen_ising_sk20(),
        "qubo_maxcut": gen_qubo_maxcut()
    }
    for name, data in instances.items():
        path = os.path.join("/app/instances", f"{name}.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Generated {path}")

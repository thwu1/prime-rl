#!/usr/bin/env python3
"""
Instance generator for the Oil Field Detection problem.

Usage: python3 generate.py <seed> [N] [M] [epsilon]
Output: JSON instance to stdout.
"""

import json
import random
import sys

SHAPES = {
    "square": [(0, 0), (0, 1), (1, 0), (1, 1)],
    "L": [(0, 0), (1, 0), (1, 1)],
    "T": [(0, 0), (0, 1), (0, 2), (1, 1)],
    "S": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "line3": [(0, 0), (1, 0), (2, 0)],
    "line4": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "plus": [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)],
}


def generate_instance(seed, N=10, M=3, epsilon=0.15, shape_names=None):
    rng = random.Random(seed)

    if shape_names is None:
        available = list(SHAPES.keys())
        shape_names = []
        for _ in range(M):
            shape_names.append(rng.choice(available))

    polyominoes = [SHAPES[name] for name in shape_names]

    placements = []
    for k in range(M):
        max_di = max(di for di, dj in polyominoes[k])
        max_dj = max(dj for di, dj in polyominoes[k])
        r = rng.randint(0, N - 1 - max_di)
        c = rng.randint(0, N - 1 - max_dj)
        placements.append([r, c])

    return {
        "N": N,
        "M": M,
        "epsilon": epsilon,
        "polyominoes": polyominoes,
        "placements": placements,
        "seed": seed,
    }


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    M = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    eps = float(sys.argv[4]) if len(sys.argv) > 4 else 0.15

    instance = generate_instance(seed, N, M, eps)
    print(json.dumps(instance, indent=2))

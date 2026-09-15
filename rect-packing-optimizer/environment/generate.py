#!/usr/bin/env python3
"""
Deterministic test-case generator for the Rectangle Ad Placement problem.
Usage: python3 generate.py <seed> <output_file>

Generation follows the AHC001 specification:
  - N = round(50 * 4^rand())  with rand() uniform in [0,1)
  - (x_i, y_i): N distinct points sampled from {0..9999}^2
  - r_i: from a random partition of 100_000_000
"""
import os
import random
import sys


def generate(seed, output_file):
    rng = random.Random(seed)

    # --- generate N ---
    n = round(50 * (4 ** rng.random()))
    n = max(50, min(n, 200))

    # --- generate N distinct (x, y) coordinates ---
    coord_set = set()
    while len(coord_set) < n:
        x = rng.randint(0, 9999)
        y = rng.randint(0, 9999)
        coord_set.add((x, y))
    coords = sorted(coord_set)   # sort for determinism across Python versions
    rng.shuffle(coords)           # then shuffle with the seeded RNG

    # --- generate areas r_i that sum to 10^8 ---
    total = 100_000_000
    cuts = sorted(rng.sample(range(1, total), n - 1))
    cuts = [0] + cuts + [total]
    areas = [cuts[i + 1] - cuts[i] for i in range(n)]

    # --- write output ---
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        f.write(f"{n}\n")
        for i in range(n):
            f.write(f"{coords[i][0]} {coords[i][1]} {areas[i]}\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <seed> <output_file>", file=sys.stderr)
        sys.exit(1)
    generate(int(sys.argv[1]), sys.argv[2])

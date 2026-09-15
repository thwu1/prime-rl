#!/usr/bin/env python3
"""Generate polyomino localization instances in multi-format storage."""
import random
import math
import os
import csv
import sqlite3

SEEDS = [314159, 271828, 161803, 141421, 173205, 223606, 244949, 264575]
GRID_SIZE = 20
NUM_POLY = 5
MIN_CELLS = 3
MAX_CELLS = 7
NUM_MEASUREMENTS = 200
NOISE_SIGMA = 0.05
MAX_REGION_DIM = 4


def generate_polyomino(rng, min_cells, max_cells):
    num_cells = rng.randint(min_cells, max_cells)
    cells = [(0, 0)]
    for _ in range(num_cells - 1):
        cell_set = set(cells)
        neighbors = set()
        for r, c in cells:
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (r + dr, c + dc)
                if nb not in cell_set:
                    neighbors.add(nb)
        candidates = sorted(neighbors)
        cells.append(candidates[rng.randint(0, len(candidates) - 1)])
    min_r = min(r for r, c in cells)
    min_c = min(c for r, c in cells)
    return sorted((r - min_r, c - min_c) for r, c in cells)


def generate_instance(seed):
    rng = random.Random(seed)
    occupied = set()
    polyominoes = []
    placements = []

    for _ in range(NUM_POLY):
        cells = generate_polyomino(rng, MIN_CELLS, MAX_CELLS)
        max_r = max(r for r, c in cells)
        max_c = max(c for r, c in cells)
        valid = []
        for dr in range(GRID_SIZE - max_r):
            for dc in range(GRID_SIZE - max_c):
                placed = frozenset((r + dr, c + dc) for r, c in cells)
                if not placed & occupied:
                    valid.append((dr, dc))
        if not valid:
            continue
        offset = valid[rng.randint(0, len(valid) - 1)]
        polyominoes.append(cells)
        placements.append(offset)
        for r, c in cells:
            occupied.add((r + offset[0], c + offset[1]))

    grid = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
    for cells, (dr, dc) in zip(polyominoes, placements):
        for r, c in cells:
            grid[r + dr][c + dc] = 1

    measurements = []
    for _ in range(NUM_MEASUREMENTS):
        r1 = rng.randint(0, GRID_SIZE - 1)
        r2 = rng.randint(r1 + 1, min(r1 + MAX_REGION_DIM, GRID_SIZE))
        c1 = rng.randint(0, GRID_SIZE - 1)
        c2 = rng.randint(c1 + 1, min(c1 + MAX_REGION_DIM, GRID_SIZE))
        true_sum = sum(grid[r][c] for r in range(r1, r2) for c in range(c1, c2))
        region_size = (r2 - r1) * (c2 - c1)
        noise = rng.gauss(0, NOISE_SIGMA * math.sqrt(region_size))
        noisy_value = round(max(0.0, true_sum + noise), 4)
        measurements.append((r1, c1, r2, c2, noisy_value))

    return polyominoes, measurements


def main():
    os.makedirs("/app/shapes", exist_ok=True)

    with open("/app/config.toml", "w") as f:
        f.write("[grid]\nsize = 20\n\n[noise]\nsigma = 0.05\n\n[instances]\ncount = 8\n")

    conn = sqlite3.connect("/app/data.db")
    cur = conn.cursor()
    cur.execute("""CREATE TABLE instances (
        id INTEGER PRIMARY KEY,
        num_polyominoes INTEGER NOT NULL
    )""")
    cur.execute("""CREATE TABLE measurements (
        instance_id INTEGER NOT NULL,
        meas_id INTEGER NOT NULL,
        region_r1 INTEGER NOT NULL,
        region_c1 INTEGER NOT NULL,
        region_r2 INTEGER NOT NULL,
        region_c2 INTEGER NOT NULL,
        noisy_value REAL NOT NULL,
        PRIMARY KEY (instance_id, meas_id),
        FOREIGN KEY (instance_id) REFERENCES instances(id)
    )""")

    for i, seed in enumerate(SEEDS):
        polys, meas = generate_instance(seed)

        inst_dir = f"/app/shapes/instance_{i}"
        os.makedirs(inst_dir, exist_ok=True)
        for j, cells in enumerate(polys):
            with open(f"{inst_dir}/poly_{j}.csv", "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["row", "col"])
                for r, c in cells:
                    writer.writerow([r, c])

        cur.execute("INSERT INTO instances VALUES (?, ?)", (i, len(polys)))
        for m_id, (r1, c1, r2, c2, val) in enumerate(meas):
            cur.execute(
                "INSERT INTO measurements VALUES (?, ?, ?, ?, ?, ?, ?)",
                (i, m_id, r1, c1, r2, c2, val)
            )

    conn.commit()
    conn.close()
    print(f"Generated {len(SEEDS)} instances")


if __name__ == "__main__":
    main()

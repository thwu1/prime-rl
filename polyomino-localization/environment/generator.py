#!/usr/bin/env python3
"""
Polyomino Localization Instance Generator.

Generates instances where polyominoes of known shapes are placed at unknown
positions on a grid, and noisy aggregate measurements over rectangular
subregions are provided.

Uses only Python stdlib for deterministic generation with random.Random.
"""
import random
import math
import json
import os

SEEDS = [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008]
GRID_SIZE = 20
NUM_POLY = 5
MIN_CELLS = 3
MAX_CELLS = 7
NUM_MEASUREMENTS = 200
NOISE_SIGMA = 0.05
MAX_REGION_DIM = 4


def generate_polyomino(rng, min_cells, max_cells):
    """Generate a random connected polyomino by growing from (0,0)."""
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
    """Generate a single problem instance from a seed.

    Returns (solver_input_dict, ground_truth_grid).
    """
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

    # Build ground truth grid
    grid = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
    for cells, (dr, dc) in zip(polyominoes, placements):
        for r, c in cells:
            grid[r + dr][c + dc] = 1

    # Generate noisy measurements
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
        measurements.append({
            "region": [r1, c1, r2, c2],
            "noisy_value": noisy_value
        })

    solver_input = {
        "grid_size": GRID_SIZE,
        "polyominoes": [
            {"id": i, "cells": list(cells)}
            for i, cells in enumerate(polyominoes)
        ],
        "measurements": measurements,
        "noise_sigma": NOISE_SIGMA
    }
    return solver_input, grid


def main():
    os.makedirs("/app/instances", exist_ok=True)
    for i, seed in enumerate(SEEDS):
        inp, _ = generate_instance(seed)
        with open(f"/app/instances/instance_{i}.json", "w") as f:
            json.dump(inp, f, indent=2)
    print(f"Generated {len(SEEDS)} instances in /app/instances/")


if __name__ == "__main__":
    main()

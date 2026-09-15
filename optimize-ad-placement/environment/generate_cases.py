#!/usr/bin/env python3
"""Generate test cases including adversarial distributions for rectangle packing."""

import random
import os

os.makedirs('/app/test_cases', exist_ok=True)


def write_case(idx, n, coords, areas):
    assert len(coords) == n and len(areas) == n
    assert len(set(coords)) == n, "Duplicate coordinates"
    assert all(a > 0 for a in areas), f"Non-positive area: {min(areas)}"
    assert sum(areas) == 100000000, f"Area sum: {sum(areas)}"
    with open(f'/app/test_cases/input_{idx:02d}.txt', 'w') as f:
        f.write(f'{n}\n')
        for i in range(n):
            f.write(f'{coords[i][0]} {coords[i][1]} {areas[i]}\n')


def rand_coords(rng, n, x_lo=0, x_hi=9999, y_lo=0, y_hi=9999):
    used = set()
    coords = []
    while len(coords) < n:
        x = rng.randint(x_lo, x_hi)
        y = rng.randint(y_lo, y_hi)
        if (x, y) not in used:
            used.add((x, y))
            coords.append((x, y))
    return coords


def stick_break_areas(rng, n):
    cuts = sorted(rng.sample(range(1, 100000000), n - 1))
    cuts = [0] + cuts + [100000000]
    return [cuts[i + 1] - cuts[i] for i in range(n)]


def normal_case(idx, seed):
    """Standard AHC001 generation: random positions, stick-breaking areas."""
    rng = random.Random(seed)
    u = rng.random()
    n = max(50, min(200, round(50 * (4 ** u))))
    coords = rand_coords(rng, n)
    areas = stick_break_areas(rng, n)
    write_case(idx, n, coords, areas)


def clustered_case(idx, seed):
    """Points in a 6000x6000 central region — forces rectangles to extend
    outside the cluster to achieve correct total area."""
    rng = random.Random(seed)
    n = 100
    coords = rand_coords(rng, n, 2000, 8000, 2000, 8000)
    areas = stick_break_areas(rng, n)
    write_case(idx, n, coords, areas)


def near_collinear_case(idx, seed):
    """X-values confined to a 100-pixel band — constrains x-axis splits and
    forces the partition to rely almost entirely on y-axis splits."""
    rng = random.Random(seed)
    n = 60
    coords = rand_coords(rng, n, 4950, 5050, 0, 9999)
    areas = stick_break_areas(rng, n)
    write_case(idx, n, coords, areas)


def extreme_areas_case(idx, seed):
    """Two dominant companies (25%+15% of total area) with 78 small
    companies sharing the remaining 60%. Tests area-balance under skew."""
    rng = random.Random(seed)
    n = 80
    coords = rand_coords(rng, n)
    big = [25000000, 15000000]
    remaining = 100000000 - sum(big)
    n_small = n - len(big)
    per_small = remaining // n_small
    areas = big + [per_small] * (n_small - 1)
    areas.append(remaining - per_small * (n_small - 1))
    rng.shuffle(areas)
    write_case(idx, n, coords, areas)


def half_plane_case(idx, seed):
    """Points all in the left 40% of the grid with varying y spread.
    Tests partition ability to allocate empty right-side space efficiently."""
    rng = random.Random(seed)
    n = 80
    coords = rand_coords(rng, n, 0, 3999, 0, 9999)
    areas = stick_break_areas(rng, n)
    write_case(idx, n, coords, areas)


# --- Generate all cases ---

# Normal distribution (5 cases)
for i, seed in enumerate([42, 137, 256, 389, 500]):
    normal_case(i, seed)

# Adversarial distributions (5 cases)
clustered_case(5, 777)
near_collinear_case(6, 888)
extreme_areas_case(7, 999)
half_plane_case(8, 1111)
normal_case(9, 2222)

print("Generated 10 test cases in /app/test_cases/")

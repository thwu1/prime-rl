#!/usr/bin/env python3
"""
Deterministic generator for Location-Routing Problem (LRP) instances.

Generates instances where candidate depot locations must be selected and
vehicle routes planned jointly. Uses only random.random() for portability
across Python versions.
"""

import math
import os
import random


def box_muller(rng, mu, sigma):
    """Deterministic Gaussian via Box-Muller (uses only rng.random())."""
    u1 = rng.random()
    while u1 == 0.0:
        u1 = rng.random()
    u2 = rng.random()
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mu + sigma * z


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def generate_instance(seed, nd, nc, vpd, vc, field_size=100.0, cluster_std=7.0):
    """
    Generate an LRP instance.

    Parameters
    ----------
    seed : int          -- RNG seed for reproducibility
    nd   : int          -- number of candidate depots
    nc   : int          -- number of customers
    vpd  : int          -- max vehicles per depot
    vc   : int          -- vehicle capacity
    """
    rng = random.Random(seed)

    # --- Depot positions on a jittered circle around the field center ---
    depots = []
    cx, cy = field_size / 2, field_size / 2
    for i in range(nd):
        angle = 2.0 * math.pi * i / nd + (rng.random() - 0.5) * 0.4
        radius = 25 + rng.random() * 20  # 25..45
        x = clamp(round(cx + radius * math.cos(angle), 1), 2.0, field_size - 2)
        y = clamp(round(cy + radius * math.sin(angle), 1), 2.0, field_size - 2)
        setup = rng.randint(200, 900)
        cap_lo = max(100, (nc * 18) // nd)
        cap_hi = max(200, (nc * 30) // nd)
        cap = rng.randint(cap_lo, cap_hi)
        depots.append((setup, cap, x, y))

    # --- Customer positions clustered around depots ---
    customers = []
    for j in range(nc):
        di = j % nd          # spread evenly across depots
        dx, dy = depots[di][2], depots[di][3]
        x = clamp(round(box_muller(rng, dx, cluster_std), 1), 0.0, field_size)
        y = clamp(round(box_muller(rng, dy, cluster_std), 1), 0.0, field_size)
        demand = rng.randint(5, 25)
        customers.append((demand, x, y))

    return depots, customers


def write_instance(path, nd, nc, vpd, vc, depots, customers):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{nd} {nc} {vpd} {vc}\n")
        for s, cap, x, y in depots:
            f.write(f"{s} {cap} {x} {y}\n")
        for d, x, y in customers:
            f.write(f"{d} {x} {y}\n")


def main():
    specs = [
        # (seed, n_depots, n_customers, vehicles_per_depot, vehicle_cap, filename)
        (42,   5,  20, 3, 50,  "/app/data/instance_1.txt"),
        (137,  8,  50, 4, 60,  "/app/data/instance_2.txt"),
        (271, 12, 100, 5, 80,  "/app/data/instance_3.txt"),
    ]
    for seed, nd, nc, vpd, vc, fname in specs:
        depots, customers = generate_instance(seed, nd, nc, vpd, vc)
        write_instance(fname, nd, nc, vpd, vc, depots, customers)
        total_demand = sum(d for d, _, _ in customers)
        total_cap = sum(c for _, c, _, _ in depots)
        print(f"{fname}: {nd} depots, {nc} custs, "
              f"demand={total_demand}, cap={total_cap}, "
              f"ratio={total_cap/total_demand:.2f}")

    os.makedirs("/app/solutions", exist_ok=True)
    os.makedirs("/app/models", exist_ok=True)
    os.makedirs("/app/logs", exist_ok=True)


if __name__ == "__main__":
    main()

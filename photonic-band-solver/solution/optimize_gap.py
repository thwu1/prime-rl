#!/usr/bin/env python3
"""
Optimize rod radius to maximise the first TM band gap of a 2D photonic crystal.
Resolves material properties from /app/data/materials.json.
"""
import json
import sys

sys.path.insert(0, "/app")
import numpy as np
from scipy.optimize import minimize_scalar

from solve_bands import compute_bands, load_materials_db


def optimize_gap(config):
    """Find the radius in [radius_min, radius_max] that maximises the
    first TM gap (between bands 1 and 2)."""
    r_min = float(config["radius_min"])
    r_max = float(config["radius_max"])

    materials_db = load_materials_db()

    base = {
        "lattice_type": config["lattice_type"],
        "rod_material": config["rod_material"],
        "background_material": config["background_material"],
        "num_bands": 2,
        "resolution": int(config.get("resolution", 20)),
        "k_interp": int(config.get("k_interp", 4)),
    }

    def neg_gap(r):
        cfg = dict(base, radius=float(r))
        results = compute_bands(cfg, materials_db=materials_db)
        for g in results["gaps"]:
            if g["from_band"] == 1 and g["to_band"] == 2:
                return -g["gap_percent"]
        return 0.0

    result = minimize_scalar(
        neg_gap,
        bounds=(r_min, r_max),
        method="bounded",
        options={"xatol": 0.005, "maxiter": 40},
    )

    return {
        "optimal_radius": float(result.x),
        "max_gap_percent": float(-result.fun),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 optimize_gap.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    result = optimize_gap(config)

    with open("/app/opt_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Optimal radius: {result['optimal_radius']:.6f}")
    print(f"Max gap percent: {result['max_gap_percent']:.2f}%")

#!/usr/bin/env python3

"""
Corrected level-1 Menger sponge construction.

Fixes applied to the original pipeline.py:
1. SDF combination: min -> max (union of prisms, not intersection)
2. Level-set bounds: extended beyond unit cube so prisms create through-holes
3. Euler characteristic formula: V + E - F -> V - E + F
"""

import json
from manifold3d import Manifold


def cross_sdf(x, y, z):
    """Signed distance function for the cross-shaped void.

    Union of three orthogonal square prisms, each with half-width s = 1/6
    in two dimensions, unbounded in the third.
    Positive inside, negative outside.
    """
    s = 1.0 / 6.0

    prism_z = min(s - abs(x), s - abs(y))
    prism_x = min(s - abs(y), s - abs(z))
    prism_y = min(s - abs(x), s - abs(z))

    # Union of SDFs (inside-positive convention) = max
    return max(prism_z, prism_x, prism_y)


def build_sponge():
    """Construct the Menger sponge and return the Manifold object."""
    cube = Manifold.cube([1.0, 1.0, 1.0], True)

    # Bounds must extend beyond the unit cube so the prisms create
    # through-holes. BoundedSDF seals the surface at domain edges;
    # placing the seal outside the cube avoids interfering with the
    # Boolean subtraction.
    margin = 0.15
    lo = -0.5 - margin
    hi = 0.5 + margin
    edge_length = 0.02

    cross = Manifold.level_set(cross_sdf, [lo, lo, lo, hi, hi, hi], edge_length)
    return cube - cross


def main():
    sponge = build_sponge()

    num_vert = sponge.num_vert()
    num_tri = sponge.num_tri()
    num_edge = 3 * num_tri // 2

    status_raw = str(sponge.status())
    status_str = status_raw.split(".")[-1] if "." in status_raw else status_raw

    result = {
        "status": status_str,
        "genus": sponge.genus(),
        "volume": sponge.volume(),
        "surface_area": sponge.surface_area(),
        "num_vert": num_vert,
        "num_tri": num_tri,
        "euler_characteristic": num_vert - num_edge + num_tri,
    }

    with open("/app/output.json", "w") as f:
        json.dump(result, f, indent=2)

    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

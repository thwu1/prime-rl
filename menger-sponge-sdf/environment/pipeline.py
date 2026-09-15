#!/usr/bin/env python3

"""Construct a level-1 Menger sponge and output its properties."""

import json
from manifold3d import Manifold


def cross_sdf(x, y, z):
    """Signed distance function for the cross-shaped void.

    Three orthogonal square prisms, each with half-width s = 1/6
    in two dimensions, unbounded in the third.
    Positive inside, negative outside.
    """
    s = 1.0 / 6.0

    prism_z = min(s - abs(x), s - abs(y))
    prism_x = min(s - abs(y), s - abs(z))
    prism_y = min(s - abs(x), s - abs(z))

    return min(prism_z, prism_x, prism_y)


def build_sponge():
    """Construct the Menger sponge and return the Manifold object."""
    cube = Manifold.cube([1.0, 1.0, 1.0], True)

    bounds = [-0.4, -0.4, -0.4, 0.4, 0.4, 0.4]
    edge_length = 0.05

    cross = Manifold.level_set(cross_sdf, bounds, edge_length)
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
        "euler_characteristic": num_vert + num_edge - num_tri,
    }

    with open("/app/output.json", "w") as f:
        json.dump(result, f, indent=2)

    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

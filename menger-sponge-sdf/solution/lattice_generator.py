#!/usr/bin/env python3

"""
Gyroid TPMS lattice infill generator.

Constructs a gyroid shell lattice clipped to a rhombic dodecahedron,
with the iso_thickness parameter tuned via bisection to achieve a
target volume fraction.
"""

import json
import math
from manifold3d import Manifold


def gyroid_sdf(x, y, z):
    """Standard gyroid implicit function. Period = 2*pi in each axis."""
    return (
        math.cos(x) * math.sin(y)
        + math.cos(y) * math.sin(z)
        + math.cos(z) * math.sin(x)
    )


def build_bounding_shape(size):
    """Construct a rhombic dodecahedron via CSG intersection of three
    rotated rectangular prisms.

    The prism dimensions use sqrt(2) scaling, and three different
    rotation orientations are intersected to form the dual of the
    cuboctahedron.
    """
    s = size * math.sqrt(2.0)
    box = Manifold.cube([s, s, 2.0 * s], True)
    result = box.rotate([90, 45, 0]) ^ box.rotate([90, 45, 90])
    return result ^ box.rotate([0, 0, 45])


def build_lattice(iso_thickness, size, num_periods, mesh_segments):
    """Build the gyroid shell lattice clipped to the bounding shape.

    The shell is the region where |gyroid_sdf| < iso_thickness,
    constructed by subtracting the inner level-set (f > +t) from
    the outer level-set (f > -t). The result is scaled from the
    gyroid's native coordinate system to fit the bounding shape,
    then intersected with the rhombic dodecahedron.

    Parameters:
        iso_thickness: half-thickness of the gyroid shell in SDF units
        size: bounding shape size parameter
        num_periods: number of complete gyroid periods (period = 2*pi)
        mesh_segments: mesh resolution (segments per one gyroid period)
    """
    period = 2.0 * math.pi
    half_extent = num_periods * math.pi
    edge_len = period / mesh_segments

    bounds = [
        -half_extent, -half_extent, -half_extent,
        half_extent, half_extent, half_extent,
    ]

    # Outer solid: region where f > -iso_thickness
    outer = Manifold.level_set(gyroid_sdf, bounds, edge_len, -iso_thickness)
    # Inner solid: region where f > +iso_thickness
    inner = Manifold.level_set(gyroid_sdf, bounds, edge_len, iso_thickness)

    # Shell = outer - inner = region where -t < f < t
    shell = outer - inner

    # Scale from gyroid coordinates to physical coordinates
    scale_factor = size / half_extent
    shell_scaled = shell.scale([scale_factor, scale_factor, scale_factor])

    # Clip to bounding shape
    rd = build_bounding_shape(size)
    return shell_scaled ^ rd


def find_iso_thickness(target_vf, tolerance, size, num_periods, mesh_segments):
    """Find iso_thickness via bisection to achieve target volume fraction.

    Volume fraction = lattice_volume / bounding_shape_volume.
    As iso_thickness increases, the shell gets thicker and VF increases
    monotonically from 0 (at t=0) to ~1 (at t~1.5).

    Parameters:
        target_vf: target volume fraction (e.g. 0.35)
        tolerance: acceptable error in volume fraction
        size: bounding shape size
        num_periods: gyroid periods
        mesh_segments: mesh resolution
    """
    rd = build_bounding_shape(size)
    rd_vol = rd.volume()

    lo = 0.01
    hi = 1.4
    best_t = (lo + hi) / 2.0
    best_err = float("inf")

    for _ in range(20):
        mid = (lo + hi) / 2.0
        lattice = build_lattice(mid, size, num_periods, mesh_segments)
        vf = lattice.volume() / rd_vol
        err = abs(vf - target_vf)

        if err < best_err:
            best_err = err
            best_t = mid

        if err < tolerance / 2.0:
            break

        if vf < target_vf:
            lo = mid
        else:
            hi = mid

    return best_t


def generate_lattice(spec_path):
    """Main driver: read spec, run pipeline, write result.json."""
    with open(spec_path) as f:
        spec = json.load(f)

    size = spec["bounding_size"]
    num_periods = spec["num_periods"]
    target_vf = spec["target_volume_fraction"]
    tolerance = spec["volume_fraction_tolerance"]
    mesh_segments = spec["mesh_segments_per_period"]

    iso_t = find_iso_thickness(
        target_vf, tolerance, size, num_periods, mesh_segments
    )

    lattice = build_lattice(iso_t, size, num_periods, mesh_segments)
    rd = build_bounding_shape(size)

    rd_vol = rd.volume()
    solid_vol = lattice.volume()

    status_raw = str(lattice.status())
    status_str = (
        status_raw.split(".")[-1] if "." in status_raw else status_raw
    )

    result = {
        "iso_thickness": iso_t,
        "volume_fraction": solid_vol / rd_vol,
        "solid_volume": solid_vol,
        "bounding_volume": rd_vol,
        "surface_area": lattice.surface_area(),
        "genus": lattice.genus(),
        "status": status_str,
        "num_vert": lattice.num_vert(),
        "num_tri": lattice.num_tri(),
    }

    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    result = generate_lattice("/app/spec.json")
    for k, v in result.items():
        print(f"{k}: {v}")

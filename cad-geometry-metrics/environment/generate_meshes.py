#!/usr/bin/env python3
"""Generate binary STL mesh files for the mesh evaluation benchmark.

Uses only stdlib (struct, math, os). No external dependencies.
Creates 5 candidate/reference pairs with varying geometry:
  1. Identical cubes
  2. Different aspect-ratio boxes
  3. Different-proportion boxes
  4. Cube with inverted face normals (defective, needs repair)
  5. Cylinder vs flat plate (very different shapes)
"""
import struct
import math
import os


def write_binary_stl(filename, triangles):
    """Write triangles as binary STL.

    Args:
        filename: output path
        triangles: list of (normal, v1, v2, v3) where each is a 3-tuple of floats
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "wb") as f:
        f.write(b"\x00" * 80)
        f.write(struct.pack("<I", len(triangles)))
        for normal, v1, v2, v3 in triangles:
            for val in list(normal) + list(v1) + list(v2) + list(v3):
                f.write(struct.pack("<f", float(val)))
            f.write(struct.pack("<H", 0))


def box_triangles(w, h, d):
    """12 triangles for an axis-aligned box of size w*h*d centred at origin.

    Outward-facing normals with consistent CCW winding (viewed from outside).
    """
    x0, x1 = -w / 2.0, w / 2.0
    y0, y1 = -h / 2.0, h / 2.0
    z0, z1 = -d / 2.0, d / 2.0

    v = [
        (x0, y0, z0),  # 0
        (x1, y0, z0),  # 1
        (x1, y1, z0),  # 2
        (x0, y1, z0),  # 3
        (x0, y0, z1),  # 4
        (x1, y0, z1),  # 5
        (x1, y1, z1),  # 6
        (x0, y1, z1),  # 7
    ]

    return [
        # -Z face
        ((0, 0, -1), v[0], v[2], v[1]),
        ((0, 0, -1), v[0], v[3], v[2]),
        # +Z face
        ((0, 0, 1), v[4], v[5], v[6]),
        ((0, 0, 1), v[4], v[6], v[7]),
        # -Y face
        ((0, -1, 0), v[0], v[1], v[5]),
        ((0, -1, 0), v[0], v[5], v[4]),
        # +Y face
        ((0, 1, 0), v[2], v[3], v[7]),
        ((0, 1, 0), v[2], v[7], v[6]),
        # -X face
        ((-1, 0, 0), v[0], v[4], v[7]),
        ((-1, 0, 0), v[0], v[7], v[3]),
        # +X face
        ((1, 0, 0), v[1], v[2], v[6]),
        ((1, 0, 0), v[1], v[6], v[5]),
    ]


def invert_triangles(triangles):
    """Invert winding order and negate normals — produces a mesh whose signed
    volume is negative and whose containment tests return inverted results."""
    return [
        ((-n[0], -n[1], -n[2]), v1, v3, v2)
        for n, v1, v2, v3 in triangles
    ]


def cylinder_triangles(radius, height, n_sides=64):
    """Triangulated closed cylinder centred at origin with outward normals."""
    tris = []
    z0, z1 = -height / 2.0, height / 2.0

    for i in range(n_sides):
        a1 = 2.0 * math.pi * i / n_sides
        a2 = 2.0 * math.pi * ((i + 1) % n_sides) / n_sides

        x1 = radius * math.cos(a1)
        y1 = radius * math.sin(a1)
        x2 = radius * math.cos(a2)
        y2 = radius * math.sin(a2)

        # Bottom cap (normal -Z)
        tris.append(((0, 0, -1), (0, 0, z0), (x2, y2, z0), (x1, y1, z0)))
        # Top cap (normal +Z)
        tris.append(((0, 0, 1), (0, 0, z1), (x1, y1, z1), (x2, y2, z1)))

        # Side — outward normal
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0
        nl = math.sqrt(mx * mx + my * my)
        nx, ny = mx / nl, my / nl

        tris.append(((nx, ny, 0), (x1, y1, z0), (x2, y2, z0), (x2, y2, z1)))
        tris.append(((nx, ny, 0), (x1, y1, z0), (x2, y2, z1), (x1, y1, z1)))

    return tris


def main():
    meshdir = "/app/meshes"

    # Pair 1: identical cubes (10x10x10)
    box10 = box_triangles(10, 10, 10)
    write_binary_stl(f"{meshdir}/cand_01.stl", box10)
    write_binary_stl(f"{meshdir}/ref_01.stl", box10)

    # Pair 2: different aspect ratios — box(10,10,5) vs box(10,5,10)
    write_binary_stl(f"{meshdir}/cand_02.stl", box_triangles(10, 10, 5))
    write_binary_stl(f"{meshdir}/ref_02.stl", box_triangles(10, 5, 10))

    # Pair 3: different proportions — box(20,5,10) vs box(15,8,10)
    write_binary_stl(f"{meshdir}/cand_03.stl", box_triangles(20, 5, 10))
    write_binary_stl(f"{meshdir}/ref_03.stl", box_triangles(15, 8, 10))

    # Pair 4: inverted normals (defective candidate) — needs repair
    box8 = box_triangles(8, 8, 8)
    write_binary_stl(f"{meshdir}/cand_04.stl", invert_triangles(box8))
    write_binary_stl(f"{meshdir}/ref_04.stl", box8)

    # Pair 5: very different shapes — cylinder(r=15,h=30) vs flat plate(30x30x2)
    write_binary_stl(f"{meshdir}/cand_05.stl", cylinder_triangles(15, 30, 64))
    write_binary_stl(f"{meshdir}/ref_05.stl", box_triangles(30, 30, 2))

    print(f"Generated {len(os.listdir(meshdir))} mesh files in {meshdir}")


if __name__ == "__main__":
    main()

"""Scene definition: transforms, composition, and material assignment.

Uses SDF primitives from the C shared library via ctypes bindings.
"""
import math
from bindings import sd_sphere, sd_torus, sd_round_box, sd_octahedron, smin_poly


# Material IDs
MAT_GROUND = 0
MAT_BLOB = 1
MAT_CRYSTAL = 2
MAT_CARVED = 3

# Material colors (R, G, B) in [0,1]
MATERIAL_COLORS = {
    MAT_GROUND: (0.5, 0.5, 0.5),
    MAT_BLOB: (0.8, 0.4, 0.1),
    MAT_CRYSTAL: (0.2, 0.3, 0.8),
    MAT_CARVED: (0.3, 0.7, 0.2),
}


def _twist_y(px, py, pz, strength):
    """Apply twist deformation around the Y axis."""
    angle = strength * py
    c = math.cos(angle)
    s = math.sin(angle)
    return c * px - s * py, s * px + c * py, pz


def scene_sdf(x, y, z):
    """Evaluate the full scene SDF at point (x,y,z).
    Returns (distance, material_id).
    """
    # Ground plane at y = -1
    d = y + 1.0
    mat = MAT_GROUND

    # Blob: smooth union of torus + sphere
    dt = sd_torus(x, y, z, 1.0, 0.25)
    ds = sd_sphere(x, y - 0.8, z, 0.35)
    d_blob = smin_poly(dt, ds, 0.4)
    if d_blob < d:
        d = d_blob
        mat = MAT_BLOB

    # Crystal: twisted octahedron at (2.2, 0.3, 0)
    cx, cy, cz = x - 2.2, y - 0.3, z
    cx, cy, cz = _twist_y(cx, cy, cz, 2.0)
    d_crystal = sd_octahedron(cx, cy, cz, 0.65)
    if d_crystal < d:
        d = d_crystal
        mat = MAT_CRYSTAL

    # Carved block: sphere subtracted from round box
    bx, by_, bz = x + 2.0, y - 0.2, z - 0.5
    d_box = sd_round_box(bx, by_, bz, 0.6, 0.6, 0.6, 0.08)
    sx, sy, sz = x + 2.0, y - 0.5, z - 0.3
    d_carve = sd_sphere(sx, sy, sz, 0.5)
    d_carved = max(d_carve, d_box)
    if d_carved < d:
        d = d_carved
        mat = MAT_CARVED

    return d, mat


def scene_sdf_dist(x, y, z):
    """Return only the distance (no material)."""
    return scene_sdf(x, y, z)[0]

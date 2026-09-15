"""SDF primitive distance functions.

Each function returns the signed distance from point (px,py,pz)
to the surface of the given primitive.
"""
import math


def sd_sphere(px, py, pz, r):
    """Signed distance to sphere centered at origin with radius r."""
    return math.sqrt(px * px + py * py + pz * pz) - r


def sd_torus(px, py, pz, R, r):
    """Signed distance to torus centered at origin.
    R = major radius, r = minor (tube) radius.
    Torus lies in the XZ plane.
    """
    q = math.sqrt(px * px + pz * pz) - R
    return abs(q) - r


def sd_round_box(px, py, pz, bx, by, bz, r):
    """Signed distance to axis-aligned rounded box centered at origin.
    (bx,by,bz) = half-extents, r = rounding radius.
    """
    qx = abs(px) - bx
    qy = abs(py) - by
    qz = abs(pz) - bz
    mx = max(qx, 0.0)
    my = max(qy, 0.0)
    mz = max(qz, 0.0)
    outer = math.sqrt(mx * mx + my * my + mz * mz)
    inner = min(max(qx, max(qy, qz)), 0.0)
    return outer + inner - r


def sd_octahedron(px, py, pz, s):
    """Exact signed distance to regular octahedron centered at origin, size s."""
    px, py, pz = abs(px), abs(py), abs(pz)
    m = px + py + pz - s
    if 3.0 * px < m:
        qx, qy, qz = px, py, pz
    elif 3.0 * py < m:
        qx, qy, qz = py, pz, px
    elif 3.0 * pz < m:
        qx, qy, qz = pz, px, py
    else:
        return m * 0.5
    k = max(0.0, min(s, 0.5 * (qz - qy + s)))
    return math.sqrt(qx * qx + (qy - s + k) ** 2 + (qz - k) ** 2)

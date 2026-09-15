"""Tests for SDF rendering pipeline correctness.

Verifies build output, numerical SDF evaluation accuracy (against an
independent reference evaluator), and rendered image quality/format.
"""

import math
import os
import pytest


# ---------------------------------------------------------------------------
# Reference SDF evaluator — independent pure-Python implementation
# ---------------------------------------------------------------------------

def _l3(x, y, z):
    return math.sqrt(x * x + y * y + z * z)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _sd_sphere(px, py, pz, r):
    return _l3(px, py, pz) - r


def _sd_torus(px, py, pz, R, r):
    q = math.sqrt(px * px + pz * pz) - R
    return math.sqrt(q * q + py * py) - r


def _sd_round_box(px, py, pz, bx, by, bz, r):
    qx = abs(px) - bx
    qy = abs(py) - by
    qz = abs(pz) - bz
    outer = _l3(max(qx, 0.0), max(qy, 0.0), max(qz, 0.0))
    inner = min(max(qx, max(qy, qz)), 0.0)
    return outer + inner - r


def _sd_octahedron(px, py, pz, s):
    px, py, pz = abs(px), abs(py), abs(pz)
    m = px + py + pz - s
    if 3.0 * px < m:
        qx, qy, qz = px, py, pz
    elif 3.0 * py < m:
        qx, qy, qz = py, pz, px
    elif 3.0 * pz < m:
        qx, qy, qz = pz, px, py
    else:
        return m * 0.57735027
    k = _clamp(0.5 * (qz - qy + s), 0.0, s)
    return _l3(qx, qy - s + k, qz - k)


def _smin(d1, d2, k):
    k4 = k * 4.0
    h = max(k4 - abs(d1 - d2), 0.0)
    return min(d1, d2) - h * h / (4.0 * k4)


def _twist_y(px, py, pz, strength):
    angle = strength * py
    c = math.cos(angle)
    s = math.sin(angle)
    return c * px + s * pz, py, -s * px + c * pz


def _ref_scene(x, y, z):
    """Reference scene SDF — returns minimum signed distance."""
    d = y + 1.0

    dt = _sd_torus(x, y, z, 1.0, 0.25)
    ds = _sd_sphere(x, y - 0.8, z, 0.35)
    d = min(d, _smin(dt, ds, 0.4))

    cx, cy, cz = x - 2.2, y - 0.3, z
    cx, cy, cz = _twist_y(cx, cy, cz, 2.0)
    d = min(d, _sd_octahedron(cx, cy, cz, 0.65))

    bx, by, bz = x + 2.0, y - 0.2, z - 0.5
    d_box = _sd_round_box(bx, by, bz, 0.6, 0.6, 0.6, 0.08)
    sx, sy, sz = x + 2.0, y - 0.5, z - 0.3
    d_carve = _sd_sphere(sx, sy, sz, 0.5)
    d = min(d, max(-d_carve, d_box))

    return d


# ---------------------------------------------------------------------------
# PPM reader
# ---------------------------------------------------------------------------

def _read_ppm(path):
    """Read a PPM file (P6 binary or P3 ASCII). Returns (w, h, pixel_bytes)."""
    with open(path, "rb") as f:
        magic = f.readline().strip()
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        parts = line.strip().split()
        w, h = int(parts[0]), int(parts[1])
        maxval = int(f.readline().strip())
        if magic == b"P6":
            pixels = f.read(w * h * 3)
        elif magic == b"P3":
            data = f.read().decode()
            vals = data.split()
            pixels = bytes(int(v) for v in vals[:w * h * 3])
        else:
            raise ValueError(f"Unsupported PPM format: {magic}")
    return w, h, pixels


# ---------------------------------------------------------------------------
# Build tests
# ---------------------------------------------------------------------------

class TestBuild:
    """Verify the shared library build pipeline."""

    def test_libsdf_exists(self):
        assert os.path.isfile("/app/libsdf.so"), \
            "libsdf.so not found — run 'make' in /app/"

    def test_libsdf_exports_all_symbols(self):
        import ctypes
        try:
            lib = ctypes.CDLL("/app/libsdf.so")
        except OSError as e:
            pytest.fail(f"Cannot load libsdf.so: {e}")
        required = ["sd_sphere", "sd_torus", "sd_round_box",
                     "sd_octahedron", "smin_poly"]
        missing = []
        for name in required:
            try:
                getattr(lib, name)
            except AttributeError:
                missing.append(name)
        assert not missing, \
            f"libsdf.so missing symbols: {missing}. Check Makefile SRCS."


# ---------------------------------------------------------------------------
# Distance tests
# ---------------------------------------------------------------------------

class TestDistances:
    """Verify SDF distance computations at query points."""

    def test_distances_file_exists(self):
        assert os.path.isfile("/app/distances.csv"), \
            "distances.csv not found at /app/distances.csv"

    def test_distances_count(self):
        queries = _load_queries()
        computed = _load_distances()
        assert len(computed) == len(queries), \
            f"Expected {len(queries)} distance values, got {len(computed)}"

    def test_distances_correct(self):
        queries = _load_queries()
        computed = _load_distances()
        assert len(computed) == len(queries), \
            f"Count mismatch: {len(computed)} vs {len(queries)}"
        tol = 2e-3
        failures = []
        for i, (q, c) in enumerate(zip(queries, computed)):
            ref = _ref_scene(*q)
            diff = abs(c - ref)
            if diff >= tol:
                failures.append(
                    f"  Query {i} at ({q[0]}, {q[1]}, {q[2]}): "
                    f"expected {ref:.6f}, got {c:.6f}, diff={diff:.6f}"
                )
        assert len(failures) == 0, (
            f"{len(failures)} of {len(queries)} distances incorrect "
            f"(tol={tol}):\n" + "\n".join(failures[:10])
        )


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------

class TestRender:
    """Verify the rendered PPM image."""

    def test_render_file_exists(self):
        assert os.path.isfile("/app/render.ppm"), \
            "render.ppm not found at /app/render.ppm"

    def test_render_valid_ppm(self):
        with open("/app/render.ppm", "rb") as f:
            magic = f.readline().strip()
        assert magic in (b"P6", b"P3"), f"Invalid PPM magic: {magic}"

    def test_render_dimensions(self):
        w, h, _ = _read_ppm("/app/render.ppm")
        assert w == 256 and h == 192, f"Expected 256x192, got {w}x{h}"

    def test_render_not_blank(self):
        w, h, px = _read_ppm("/app/render.ppm")
        groups = set()
        for i in range(0, len(px), 3):
            groups.add((px[i] >> 4, px[i + 1] >> 4, px[i + 2] >> 4))
            if len(groups) > 10:
                break
        assert len(groups) > 5, \
            f"Image appears blank or uniform ({len(groups)} color groups)"

    def test_render_has_sky(self):
        """Top rows should contain sky (blue-dominant pixels)."""
        w, h, px = _read_ppm("/app/render.ppm")
        blue_count = 0
        total = 0
        for y in range(h // 10):
            for x in range(0, w, 4):
                idx = (y * w + x) * 3
                r, g, b = px[idx], px[idx + 1], px[idx + 2]
                if b > r and b > 100:
                    blue_count += 1
                total += 1
        assert blue_count > total * 0.3, (
            f"Top of image should contain sky. "
            f"Only {blue_count}/{total} blue-dominant pixels found"
        )

    def test_render_has_objects(self):
        """Image should have dark, mid-tone, and bright regions."""
        w, h, px = _read_ppm("/app/render.ppm")
        bright = mid = 0
        total = w * h
        for i in range(0, len(px), 3):
            lum = px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114
            if lum > 180:
                bright += 1
            elif 30 < lum < 180:
                mid += 1
        assert mid > total * 0.05, \
            f"Image lacks mid-tone pixels (objects). Found {mid}/{total}"
        assert bright > total * 0.03, \
            f"Image lacks bright pixels. Found {bright}/{total}"

    def test_render_material_variety(self):
        """Image should contain at least 2 distinct material hues."""
        w, h, px = _read_ppm("/app/render.ppm")
        has_warm = False
        has_cool = False
        has_green = False
        for i in range(0, len(px), 3 * 4):
            if i + 2 >= len(px):
                break
            r, g, b = px[i], px[i + 1], px[i + 2]
            if r > 120 and g < r and b < r * 0.5:
                has_warm = True
            if b > 100 and b > r and b > g:
                has_cool = True
            if g > 100 and g > r and g > b:
                has_green = True
        found = sum([has_warm, has_cool, has_green])
        assert found >= 2, (
            f"Expected >=2 material colors; "
            f"warm={has_warm}, cool={has_cool}, green={has_green}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_queries():
    pts = []
    with open("/app/eval_points.csv") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(",")
                pts.append((float(parts[0]), float(parts[1]), float(parts[2])))
    return pts


def _load_distances():
    vals = []
    with open("/app/distances.csv") as f:
        for line in f:
            line = line.strip()
            if line:
                vals.append(float(line))
    return vals

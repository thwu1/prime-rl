#!/usr/bin/env python3
"""CPU SDF Raymarcher — evaluates scene distances and renders to PPM.

Implements Inigo Quilez's SDF primitives, smooth boolean operations,
domain transformations, sphere-tracing, AO, soft shadows, and
Blinn-Phong shading.
"""

import math
import sys

# ── Vector helpers (tuples) ─────────────────────────────────────────────────

def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)

def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def vlen(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])

def vnorm(a):
    l = vlen(a)
    if l < 1e-12:
        return (0.0, 1.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)

def vcross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def vmix(a, b, t):
    s = 1.0 - t
    return (a[0] * s + b[0] * t, a[1] * s + b[1] * t, a[2] * s + b[2] * t)

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# ── SDF Primitives ──────────────────────────────────────────────────────────

def sd_sphere(p, r):
    return vlen(p) - r

def sd_torus(p, R, r):
    # p.xz -> (p[0], p[2])
    qx = math.sqrt(p[0] * p[0] + p[2] * p[2]) - R
    return math.sqrt(qx * qx + p[1] * p[1]) - r

def sd_round_box(p, b, r):
    qx = abs(p[0]) - b[0] + r
    qy = abs(p[1]) - b[1] + r
    qz = abs(p[2]) - b[2] + r
    outer = math.sqrt(max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2 + max(qz, 0.0) ** 2)
    inner = min(max(qx, max(qy, qz)), 0.0)
    return outer + inner - r

def sd_octahedron(p, s):
    px = abs(p[0])
    py = abs(p[1])
    pz = abs(p[2])
    m = px + py + pz - s
    if 3.0 * px < m:
        qx, qy, qz = px, py, pz
    elif 3.0 * py < m:
        qx, qy, qz = py, pz, px
    elif 3.0 * pz < m:
        qx, qy, qz = pz, px, py
    else:
        return m * 0.57735027
    k = clamp(0.5 * (qz - qy + s), 0.0, s)
    return math.sqrt(qx * qx + (qy - s + k) ** 2 + (qz - k) ** 2)

# ── Operations ──────────────────────────────────────────────────────────────

def op_smooth_union(d1, d2, k):
    k4 = k * 4.0
    h = max(k4 - abs(d1 - d2), 0.0)
    return min(d1, d2) - h * h * 0.25 / k4

def op_subtraction(d1, d2):
    return max(-d1, d2)

# ── Transformations ─────────────────────────────────────────────────────────

def twist_y(p, strength):
    angle = strength * p[1]
    c = math.cos(angle)
    s = math.sin(angle)
    return (c * p[0] + s * p[2], p[1], -s * p[0] + c * p[2])

# ── Scene ───────────────────────────────────────────────────────────────────

COLORS = (
    (0.5, 0.5, 0.5),  # 0 ground
    (0.8, 0.4, 0.1),  # 1 blob
    (0.2, 0.3, 0.8),  # 2 crystal
    (0.3, 0.7, 0.2),  # 3 carved
)

def scene_sdf(p):
    """Return (distance, material_id)."""
    # Ground
    d = p[1] + 1.0
    mat = 0

    # Blob: smooth union torus + sphere
    dt = sd_torus(p, 1.0, 0.25)
    ds = sd_sphere(vsub(p, (0.0, 0.8, 0.0)), 0.35)
    db = op_smooth_union(dt, ds, 0.4)
    if db < d:
        d = db
        mat = 1

    # Crystal: twisted octahedron
    pc = vsub(p, (2.2, 0.3, 0.0))
    pt = twist_y(pc, 2.0)
    dc = sd_octahedron(pt, 0.65)
    if dc < d:
        d = dc
        mat = 2

    # Carved block: round box minus sphere
    pb = vsub(p, (-2.0, 0.2, 0.5))
    d_box = sd_round_box(pb, (0.6, 0.6, 0.6), 0.08)
    ps = vsub(p, (-2.0, 0.5, 0.3))
    d_sph = sd_sphere(ps, 0.5)
    dv = op_subtraction(d_sph, d_box)
    if dv < d:
        d = dv
        mat = 3

    return d, mat

def scene_dist(p):
    return scene_sdf(p)[0]

# ── Rendering constants ────────────────────────────────────────────────────

LIGHT_DIR = vnorm((0.6, 0.8, 0.5))
CAM_POS = (0.0, 2.5, 6.0)
CAM_TGT = (0.0, 0.0, 0.0)
W = 256
H = 192
MAX_STEPS = 200
HIT_EPS = 5e-4
MAX_DIST = 50.0
NORM_EPS = 5e-4

# ── Rendering routines ─────────────────────────────────────────────────────

def calc_normal(p):
    e = NORM_EPS
    dx = scene_dist((p[0] + e, p[1], p[2])) - scene_dist((p[0] - e, p[1], p[2]))
    dy = scene_dist((p[0], p[1] + e, p[2])) - scene_dist((p[0], p[1] - e, p[2]))
    dz = scene_dist((p[0], p[1], p[2] + e)) - scene_dist((p[0], p[1], p[2] - e))
    return vnorm((dx, dy, dz))

def calc_ao(p, n):
    occ = 0.0
    sca = 1.0
    for i in range(5):
        h = 0.01 + 0.12 * i / 4.0
        sample = vadd(p, vmul(n, h))
        d = scene_dist(sample)
        occ += (h - d) * sca
        sca *= 0.95
    return clamp(1.0 - 3.0 * occ, 0.0, 1.0)

def calc_soft_shadow(ro, rd, tmin, tmax):
    res = 1.0
    t = tmin
    for _ in range(64):
        if t > tmax:
            break
        h = scene_dist(vadd(ro, vmul(rd, t)))
        if h < HIT_EPS * 0.5:
            return 0.0
        res = min(res, 16.0 * h / t)
        t += clamp(h, 0.02, 0.2)
    return clamp(res, 0.0, 1.0)

def raymarch(ro, rd):
    t = 0.0
    for _ in range(MAX_STEPS):
        p = vadd(ro, vmul(rd, t))
        d, mat = scene_sdf(p)
        if d < HIT_EPS:
            return t, mat
        if t > MAX_DIST:
            break
        t += d
    return -1.0, -1

def shade(ro, rd, t, mat):
    p = vadd(ro, vmul(rd, t))
    n = calc_normal(p)
    col = COLORS[mat]

    # Diffuse
    diff = max(vdot(n, LIGHT_DIR), 0.0)

    # Blinn-Phong specular
    view = vnorm(vsub(ro, p))
    half_v = vnorm(vadd(LIGHT_DIR, view))
    spec = max(vdot(n, half_v), 0.0) ** 32

    # Ambient occlusion
    ao = calc_ao(p, n)

    # Soft shadow
    sh_orig = vadd(p, vmul(n, 0.01))
    sh = calc_soft_shadow(sh_orig, LIGHT_DIR, 0.02, 10.0)

    # Combine
    lit = 0.15 * ao + 0.7 * diff * sh + 0.15 * spec * sh

    r = clamp(col[0] * lit, 0.0, 1.0)
    g = clamp(col[1] * lit, 0.0, 1.0)
    b = clamp(col[2] * lit, 0.0, 1.0)

    # Sqrt gamma
    return (math.sqrt(r), math.sqrt(g), math.sqrt(b))

def sky(rd):
    t = clamp(0.5 * (rd[1] + 1.0), 0.0, 1.0)
    return vmix((1.0, 1.0, 1.0), (0.5, 0.7, 1.0), t)

# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # ── 1. Compute distances at query points ──
    queries = []
    with open("/app/queries.csv") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(",")
                queries.append((float(parts[0]), float(parts[1]), float(parts[2])))

    with open("/app/distances.csv", "w") as f:
        for q in queries:
            d = scene_dist(q)
            f.write(f"{d:.8f}\n")
    print(f"Computed {len(queries)} distances.", file=sys.stderr)

    # ── 2. Set up camera ──
    fwd = vnorm(vsub(CAM_TGT, CAM_POS))
    right = vnorm(vcross(fwd, (0.0, 1.0, 0.0)))
    up = vcross(right, fwd)

    fov_half = math.tan(math.radians(25.0))
    aspect = W / H

    # ── 3. Render ──
    pixels = bytearray(W * H * 3)

    for j in range(H):
        if j % 32 == 0:
            print(f"Rendering row {j}/{H}...", file=sys.stderr)
        for i in range(W):
            u = (2.0 * (i + 0.5) / W - 1.0) * aspect * fov_half
            v = (1.0 - 2.0 * (j + 0.5) / H) * fov_half

            rd = vnorm(vadd(vadd(fwd, vmul(right, u)), vmul(up, v)))

            t, mat = raymarch(CAM_POS, rd)

            if t > 0.0:
                col = shade(CAM_POS, rd, t, mat)
            else:
                col = sky(rd)

            idx = (j * W + i) * 3
            pixels[idx]     = max(0, min(255, int(col[0] * 255.999)))
            pixels[idx + 1] = max(0, min(255, int(col[1] * 255.999)))
            pixels[idx + 2] = max(0, min(255, int(col[2] * 255.999)))

    # ── 4. Write PPM ──
    with open("/app/render.ppm", "wb") as f:
        f.write(f"P6\n{W} {H}\n255\n".encode())
        f.write(bytes(pixels))

    print("Render complete.", file=sys.stderr)


if __name__ == "__main__":
    main()

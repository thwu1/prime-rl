#!/usr/bin/env python3
"""SDF scene renderer — sphere-tracing raymarcher with Blinn-Phong shading.

Reads query points from /app/eval_points.csv, evaluates the scene SDF,
writes distances to /app/distances.csv, and renders to /app/render.ppm.
"""
import math
import sys

from scene import scene_sdf, scene_sdf_dist, MATERIAL_COLORS


# -- Vector helpers ----------------------------------------------------------

def v_add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

def v_sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def v_mul(a, s):
    return (a[0]*s, a[1]*s, a[2]*s)

def v_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def v_cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def v_len(a):
    return math.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2])

def v_norm(a):
    l = v_len(a) + 1e-30
    return (a[0]/l, a[1]/l, a[2]/l)

def v_clamp01(a):
    return (max(0,min(1,a[0])), max(0,min(1,a[1])), max(0,min(1,a[2])))


# -- Camera ------------------------------------------------------------------

CAM_POS = (0.0, 2.5, 6.0)
CAM_TARGET = (0.0, 0.0, 0.0)
CAM_UP = (0.0, 1.0, 0.0)
CAM_HALF_ANGLE_DEG = 25.0
IMG_W, IMG_H = 256, 192


def build_camera():
    fwd = v_norm(v_sub(CAM_TARGET, CAM_POS))
    right = v_norm(v_cross(fwd, CAM_UP))
    up = v_cross(right, fwd)
    half_h = math.tan(math.radians(CAM_HALF_ANGLE_DEG))
    half_w = half_h * IMG_W / IMG_H
    return fwd, right, up, half_w, half_h


# -- Normal computation -----------------------------------------------------

def compute_normal(x, y, z):
    e = 5e-4
    nx = scene_sdf_dist(x + e, y, z) - scene_sdf_dist(x - e, y, z)
    ny = scene_sdf_dist(x, y + e, z) - scene_sdf_dist(x, y - e, z)
    nz = scene_sdf_dist(x, y, z + e) - scene_sdf_dist(x, y, z - e)
    return v_norm((nx, ny, nz))


# -- Ambient occlusion -------------------------------------------------------

def compute_ao(x, y, z, nx, ny, nz):
    occ = 0.0
    scale = 1.0
    for i in range(1, 6):
        t = 0.02 * i
        px, py, pz = x + nx * t, y + ny * t, z + nz * t
        d = scene_sdf_dist(px, py, pz)
        occ += (t - d) * scale
        scale *= 0.5
    return max(0.0, min(1.0, 1.0 - 2.0 * occ))


# -- Soft shadow -------------------------------------------------------------

def soft_shadow(ox, oy, oz, dx, dy, dz, k=16.0, t_min=0.02, t_max=5.0):
    res = 1.0
    t = t_min
    for _ in range(64):
        if t > t_max:
            break
        px, py, pz = ox + dx * t, oy + dy * t, oz + dz * t
        h = scene_sdf_dist(px, py, pz)
        if h < 1e-4:
            return 0.0
        res = min(res, k * h / t)
        t += max(h, 0.01)
    return max(0.0, min(1.0, res))


# -- Sphere tracing ----------------------------------------------------------

MAX_STEPS = 200
HIT_THRESHOLD = 5e-4
MAX_DIST = 50.0


def trace_ray(ox, oy, oz, dx, dy, dz):
    t = 0.0
    for _ in range(MAX_STEPS):
        px = ox + dx * t
        py = oy + dy * t
        pz = oz + dz * t
        d, mat = scene_sdf(px, py, pz)
        if d < HIT_THRESHOLD:
            return t, mat
        t += d
        if t > MAX_DIST:
            break
    return -1.0, -1


# -- Shading -----------------------------------------------------------------

LIGHT_DIR = v_norm((0.6, 0.8, 0.5))
AMBIENT = 0.15
DIFFUSE = 0.70
SPECULAR = 0.15
SPEC_EXP = 32


def shade(t, mat, rd):
    px = CAM_POS[0] + rd[0] * t
    py = CAM_POS[1] + rd[1] * t
    pz = CAM_POS[2] + rd[2] * t

    n = compute_normal(px, py, pz)
    ao = compute_ao(px, py, pz, n[0], n[1], n[2])
    sh = soft_shadow(px + n[0]*0.01, py + n[1]*0.01, pz + n[2]*0.01,
                     LIGHT_DIR[0], LIGHT_DIR[1], LIGHT_DIR[2])

    diff = max(0.0, v_dot(n, LIGHT_DIR))
    half_v = v_norm(v_sub(LIGHT_DIR, rd))
    spec = max(0.0, v_dot(n, half_v)) ** SPEC_EXP

    base_color = MATERIAL_COLORS.get(mat, (0.5, 0.5, 0.5))
    lit = (
        base_color[0] * (AMBIENT * ao + DIFFUSE * diff * sh) + SPECULAR * spec * sh,
        base_color[1] * (AMBIENT * ao + DIFFUSE * diff * sh) + SPECULAR * spec * sh,
        base_color[2] * (AMBIENT * ao + DIFFUSE * diff * sh) + SPECULAR * spec * sh,
    )
    # sqrt gamma
    return (math.sqrt(max(0, lit[0])), math.sqrt(max(0, lit[1])), math.sqrt(max(0, lit[2])))


def sky_color(rd):
    t = 0.5 * (rd[1] + 1.0)
    return (1.0 - 0.5 * t, 1.0 - 0.3 * t, 1.0)


# -- Main --------------------------------------------------------------------

def evaluate_distances(input_path, output_path):
    points = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(",")
                points.append((float(parts[0]), float(parts[1]), float(parts[2])))
    with open(output_path, "w") as f:
        for x, y, z in points:
            d = scene_sdf_dist(x, y, z)
            f.write(f"{d:.6f}\n")
    return len(points)


def render(output_path):
    fwd, right, up, half_w, half_h = build_camera()
    pixels = bytearray(IMG_W * IMG_H * 3)

    for j in range(IMG_H):
        if j % 20 == 0:
            print(f"  row {j}/{IMG_H}", file=sys.stderr)
        for i in range(IMG_W):
            u = (2.0 * (i + 0.5) / IMG_W - 1.0) * half_w
            v = (1.0 - 2.0 * (j + 0.5) / IMG_H) * half_h
            rd = v_norm(v_add(v_add(fwd, v_mul(right, u)), v_mul(up, v)))
            t, mat = trace_ray(CAM_POS[0], CAM_POS[1], CAM_POS[2],
                               rd[0], rd[1], rd[2])
            if t > 0:
                col = shade(t, mat, rd)
            else:
                col = sky_color(rd)
            col = v_clamp01(col)
            idx = (j * IMG_W + i) * 3
            pixels[idx] = int(col[0] * 255)
            pixels[idx + 1] = int(col[1] * 255)
            pixels[idx + 2] = int(col[2] * 255)

    with open(output_path, "wb") as f:
        f.write(f"P6\n{IMG_W} {IMG_H}\n255\n".encode())
        f.write(bytes(pixels))


if __name__ == "__main__":
    print("Evaluating distances...", file=sys.stderr)
    n = evaluate_distances("/app/eval_points.csv", "/app/distances.csv")
    print(f"  wrote {n} distances to /app/distances.csv", file=sys.stderr)

    print("Rendering scene...", file=sys.stderr)
    render("/app/render.ppm")
    print("  wrote /app/render.ppm", file=sys.stderr)
    print("Done.", file=sys.stderr)

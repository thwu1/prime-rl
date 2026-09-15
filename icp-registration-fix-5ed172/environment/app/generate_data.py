#!/usr/bin/env python3
"""Generate synthetic point cloud data for registration testing.
Uses only Python stdlib — no numpy or other pip packages required.
"""
import math
import random
import os
import sys


def rodrigues(axis, angle_rad):
    """3x3 rotation matrix via Rodrigues' formula."""
    norm = math.sqrt(sum(a * a for a in axis))
    kx, ky, kz = (a / norm for a in axis)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    t = 1.0 - c
    return [
        [t * kx * kx + c,      t * kx * ky - s * kz, t * kx * kz + s * ky],
        [t * kx * ky + s * kz, t * ky * ky + c,      t * ky * kz - s * kx],
        [t * kx * kz - s * ky, t * ky * kz + s * kx, t * kz * kz + c     ],
    ]


def apply_transform(R, tvec, pt):
    return [
        R[0][0] * pt[0] + R[0][1] * pt[1] + R[0][2] * pt[2] + tvec[0],
        R[1][0] * pt[0] + R[1][1] * pt[1] + R[1][2] * pt[2] + tvec[1],
        R[2][0] * pt[0] + R[2][1] * pt[1] + R[2][2] * pt[2] + tvec[2],
    ]


def write_pcd(filename, points):
    N = len(points)
    with open(filename, "w") as f:
        f.write("# .PCD v0.7 - Point Cloud Data file format\n")
        f.write("VERSION 0.7\n")
        f.write("FIELDS x y z\n")
        f.write("SIZE 4 4 4\n")
        f.write("TYPE F F F\n")
        f.write("COUNT 1 1 1\n")
        f.write(f"WIDTH {N}\n")
        f.write("HEIGHT 1\n")
        f.write("VIEWPOINT 0 0 0 1 0 0 0\n")
        f.write(f"POINTS {N}\n")
        f.write("DATA ascii\n")
        for p in points:
            f.write(f"{p[0]:.8f} {p[1]:.8f} {p[2]:.8f}\n")


def main():
    # ---------- defaults ----------
    seed = 42
    rot_deg = 20.0
    rot_axis = [1.0, 2.0, 3.0]
    translation = [0.03, -0.02, 0.05]
    output_dir = "/app/data"

    # ---------- simple CLI arg parser ----------
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--seed":
            seed = int(sys.argv[i + 1]); i += 2
        elif arg == "--rotation-deg":
            rot_deg = float(sys.argv[i + 1]); i += 2
        elif arg == "--axis":
            rot_axis = [float(sys.argv[i + 1]),
                        float(sys.argv[i + 2]),
                        float(sys.argv[i + 3])]; i += 4
        elif arg == "--translation":
            translation = [float(sys.argv[i + 1]),
                           float(sys.argv[i + 2]),
                           float(sys.argv[i + 3])]; i += 4
        elif arg == "--output-dir":
            output_dir = sys.argv[i + 1]; i += 2
        else:
            i += 1

    random.seed(seed)
    os.makedirs(output_dir, exist_ok=True)

    # ---------- generate source points on a curved surface ----------
    N = 300
    nx, ny = 18, 17          # grid that produces 306 points (we trim to N)
    source = []
    for ix in range(nx):
        for iy in range(ny):
            if len(source) >= N:
                break
            x = -0.8 + 1.6 * ix / (nx - 1)
            y = -0.8 + 1.6 * iy / (ny - 1)
            z = (0.3 * (x * x + y * y)
                 + 0.1 * math.sin(3.0 * x) * math.cos(2.0 * y))
            x += random.gauss(0, 0.002)
            y += random.gauss(0, 0.002)
            z += random.gauss(0, 0.002)
            source.append([x, y, z])

    while len(source) < N:
        x = random.uniform(-0.8, 0.8)
        y = random.uniform(-0.8, 0.8)
        z = (0.3 * (x * x + y * y)
             + 0.1 * math.sin(3.0 * x) * math.cos(2.0 * y))
        x += random.gauss(0, 0.002)
        y += random.gauss(0, 0.002)
        z += random.gauss(0, 0.002)
        source.append([x, y, z])
    source = source[:N]

    # ---------- ground truth rigid transform ----------
    R = rodrigues(rot_axis, math.radians(rot_deg))

    # ---------- create target = R * source + t + noise + outliers ----------
    target = []
    for pt in source:
        tp = apply_transform(R, translation, pt)
        tp[0] += random.gauss(0, 0.002)
        tp[1] += random.gauss(0, 0.002)
        tp[2] += random.gauss(0, 0.002)
        target.append(tp)

    n_outliers = int(0.05 * N)
    outlier_indices = random.sample(range(N), n_outliers)
    for idx in outlier_indices:
        target[idx][0] += random.gauss(0, 0.1)
        target[idx][1] += random.gauss(0, 0.1)
        target[idx][2] += random.gauss(0, 0.1)

    # ---------- write outputs ----------
    write_pcd(os.path.join(output_dir, "source.pcd"), source)
    write_pcd(os.path.join(output_dir, "target.pcd"), target)

    gt_path = os.path.join(output_dir, "ground_truth.txt")
    with open(gt_path, "w") as f:
        for row in range(3):
            vals = R[row] + [translation[row]]
            f.write(" ".join(f"{v:.10f}" for v in vals) + "\n")
        f.write("0.0000000000 0.0000000000 0.0000000000 1.0000000000\n")

    print(f"Generated {N} source points, {N} target points "
          f"({n_outliers} outliers), seed={seed}")


if __name__ == "__main__":
    main()

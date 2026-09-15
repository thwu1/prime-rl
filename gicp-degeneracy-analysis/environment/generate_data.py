#!/usr/bin/env python3
"""Generate point cloud registration scan pairs with known rigid transforms."""
import numpy as np
import os


def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def rot_axis_angle(axis, angle):
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    K = skew(axis)
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def make_T(R, t):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def transform_pts(pts, T):
    return pts @ T[:3, :3].T + T[:3, 3]


def save_scan(path, target, source):
    os.makedirs(path, exist_ok=True)
    np.savetxt(os.path.join(path, "target.txt"), target, fmt="%.8f")
    np.savetxt(os.path.join(path, "source.txt"), source, fmt="%.8f")


base = "/app/scans"

# ---- Scan 1: Box surface (6 faces) — non-degenerate ----
rng = np.random.RandomState(8801)
pts_list = []
for face in range(6):
    dim, sign = face // 2, (-1) ** (face % 2)
    coords = rng.uniform(-2.5, 2.5, (500, 3))
    coords[:, dim] = sign * 2.5
    pts_list.append(coords)
surface1 = np.vstack(pts_list)
R1 = rot_axis_angle([0, 0, 1], np.radians(10))
t1 = np.array([0.30, 0.12, 0.08])
T1 = make_T(R1, t1)
target1 = surface1 + rng.normal(0, 0.01, surface1.shape)
source1 = transform_pts(surface1, np.linalg.inv(T1)) + rng.normal(0, 0.01, surface1.shape)
save_scan(f"{base}/scan_1", target1, source1)

# ---- Scan 2: Room corner (three perpendicular walls) — non-degenerate ----
rng2 = np.random.RandomState(8802)
n_w = 1000
# Floor: z = 0, x in [-4, 4], y in [-4, 4]
floor_pts = np.column_stack([
    rng2.uniform(-4, 4, n_w),
    rng2.uniform(-4, 4, n_w),
    np.zeros(n_w),
])
# Back wall: y = 4, x in [-4, 4], z in [0, 4]
back_pts = np.column_stack([
    rng2.uniform(-4, 4, n_w),
    np.full(n_w, 4.0),
    rng2.uniform(0, 4, n_w),
])
# Side wall: x = -4, y in [-4, 4], z in [0, 4]
side_pts = np.column_stack([
    np.full(n_w, -4.0),
    rng2.uniform(-4, 4, n_w),
    rng2.uniform(0, 4, n_w),
])
surface2 = np.vstack([floor_pts, back_pts, side_pts])
R2 = rot_axis_angle([0.4, 0.6, 0.7], np.radians(5))
t2 = np.array([0.15, -0.10, 0.12])
T2 = make_T(R2, t2)
target2 = surface2 + rng2.normal(0, 0.01, surface2.shape)
source2 = transform_pts(surface2, np.linalg.inv(T2)) + rng2.normal(0, 0.01, surface2.shape)
save_scan(f"{base}/scan_2", target2, source2)

# ---- Scan 3: Flat XY plane — degenerate ----
rng3 = np.random.RandomState(8803)
n3 = 3000
surface3 = np.column_stack([
    rng3.uniform(-5, 5, n3),
    rng3.uniform(-5, 5, n3),
    rng3.normal(0, 0.003, n3),
])
R3 = rot_axis_angle([0, 0, 1], np.radians(4))
t3 = np.array([0.12, 0.08, 0.25])
T3 = make_T(R3, t3)
noise3t = np.column_stack([rng3.normal(0, 0.003, n3),
                           rng3.normal(0, 0.003, n3),
                           rng3.normal(0, 0.001, n3)])
target3 = surface3 + noise3t
noise3s = np.column_stack([rng3.normal(0, 0.003, n3),
                           rng3.normal(0, 0.003, n3),
                           rng3.normal(0, 0.001, n3)])
source3 = transform_pts(surface3, np.linalg.inv(T3)) + noise3s
save_scan(f"{base}/scan_3", target3, source3)

# ---- Scan 4: Tunnel (cylinder along x-axis) — degenerate ----
rng4 = np.random.RandomState(8804)
n4 = 3000
theta4 = rng4.uniform(0, 2 * np.pi, n4)
x4 = rng4.uniform(0, 20, n4)
surface4 = np.column_stack([x4, 3.0 * np.cos(theta4), 3.0 * np.sin(theta4)])
surface4 += rng4.normal(0, 0.02, surface4.shape)
R4 = rot_axis_angle([1, 0, 0], np.radians(4))
t4 = np.array([0.70, 0.12, 0.08])
T4 = make_T(R4, t4)
target4 = surface4 + rng4.normal(0, 0.02, surface4.shape)
source4 = transform_pts(surface4, np.linalg.inv(T4)) + rng4.normal(0, 0.02, surface4.shape)
save_scan(f"{base}/scan_4", target4, source4)

# ---- Scan 5: Box surface with outlier contamination — non-degenerate ----
rng5 = np.random.RandomState(8805)
pts5 = []
for face in range(6):
    dim, sign = face // 2, (-1) ** (face % 2)
    coords = rng5.uniform(-3, 3, (500, 3))
    coords[:, dim] = sign * 3.0
    pts5.append(coords)
surface5 = np.vstack(pts5)
R5 = rot_axis_angle([1, 1, 1], np.radians(8))
t5 = np.array([0.18, 0.22, 0.12])
T5 = make_T(R5, t5)
n_out = 300
target5 = surface5 + rng5.normal(0, 0.04, surface5.shape)
target5 = np.vstack([target5, rng5.uniform(-5, 5, (n_out, 3))])
source5 = transform_pts(surface5, np.linalg.inv(T5)) + rng5.normal(0, 0.04, surface5.shape)
source5 = np.vstack([source5, rng5.uniform(-5, 5, (n_out, 3))])
save_scan(f"{base}/scan_5", target5, source5)

print("Generated 5 scan pairs in", base)

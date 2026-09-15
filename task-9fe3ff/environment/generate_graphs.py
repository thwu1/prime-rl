#!/usr/bin/env python3
"""Generate pose graph test files for the optimizer task."""
import math
import os

PI = math.pi


def normalize_angle(a):
    while a > PI:
        a -= 2 * PI
    while a < -PI:
        a += 2 * PI
    return a


def compute_relative(xi, yi, ti, xj, yj, tj):
    """Compute relative SE(2) measurement from pose i to pose j."""
    c, s = math.cos(ti), math.sin(ti)
    dx = c * (xj - xi) + s * (yj - yi)
    dy = -s * (xj - xi) + c * (yj - yi)
    dt = normalize_angle(tj - ti)
    return dx, dy, dt


def compose_pose(x, y, t, dx, dy, dt):
    """Compose a global pose with a relative measurement."""
    c, s = math.cos(t), math.sin(t)
    nx = x + c * dx - s * dy
    ny = y + s * dx + c * dy
    nt = normalize_angle(t + dt)
    return nx, ny, nt


# Ground truth: 8-node square loop (4m x 4m)
ground_truth = [
    (0.0, 0.0, 0.0),
    (2.0, 0.0, 0.0),
    (4.0, 0.0, PI / 2),
    (4.0, 2.0, PI / 2),
    (4.0, 4.0, PI),
    (2.0, 4.0, PI),
    (0.0, 4.0, -PI / 2),
    (0.0, 2.0, -PI / 2),
]

# Compute true relative measurements for sequential edges + loop closure
true_edges = []
for i in range(7):
    dx, dy, dt = compute_relative(*ground_truth[i], *ground_truth[i + 1])
    true_edges.append((i, i + 1, dx, dy, dt))
dx, dy, dt = compute_relative(*ground_truth[7], *ground_truth[0])
true_edges.append((7, 0, dx, dy, dt))

# Fixed noise values for each edge (no random dependency, fully reproducible)
# Format: (translation_x_noise, translation_y_noise, rotation_noise)
edge_noise = [
    (0.020, -0.010, 0.008),
    (-0.030, 0.020, -0.010),
    (0.015, -0.005, 0.012),
    (-0.020, 0.015, -0.008),
    (0.025, -0.020, 0.005),
    (-0.010, 0.025, -0.015),
    (0.030, -0.015, 0.010),
    (0.000, 0.000, 0.000),   # loop closure: exact measurement
]

# Create noisy edge measurements
noisy_edges = []
for (n1, n2, dx, dy, dt), (nx, ny, nt) in zip(true_edges, edge_noise):
    noisy_edges.append((n1, n2, dx + nx, dy + ny, dt + nt))

# Integrate noisy odometry to get initial vertex positions (accumulated drift)
init_poses = [(0.0, 0.0, 0.0)]
for i in range(7):
    _, _, dx, dy, dt = noisy_edges[i]
    x, y, t = init_poses[-1]
    nx, ny, nt = compose_pose(x, y, t, dx, dy, dt)
    init_poses.append((nx, ny, nt))

# Information matrix strings (upper-triangular of 3x3)
INFO_ODOM = "500.0 0.0 0.0 500.0 0.0 500.0"
INFO_LOOP = "700.0 0.0 0.0 700.0 0.0 700.0"
INFO_OUTLIER = "100.0 0.0 0.0 100.0 0.0 100.0"

os.makedirs("/app/graphs", exist_ok=True)

# --- Clean graph: odometry + loop closure, no outliers ---
with open("/app/graphs/square_loop.g2o", "w") as f:
    for i, (x, y, t) in enumerate(init_poses):
        f.write("VERTEX_SE2 %d %.10f %.10f %.10f\n" % (i, x, y, t))
    f.write("FIX 0\n")
    for n1, n2, dx, dy, dt in noisy_edges:
        info = INFO_LOOP if (n1 == 7 and n2 == 0) else INFO_ODOM
        f.write("EDGE_SE2 %d %d %.10f %.10f %.10f %s\n" % (n1, n2, dx, dy, dt, info))

# --- Corrupted graph: same edges + 2 outlier cross-loop edges ---
with open("/app/graphs/corrupted_loop.g2o", "w") as f:
    for i, (x, y, t) in enumerate(init_poses):
        f.write("VERTEX_SE2 %d %.10f %.10f %.10f\n" % (i, x, y, t))
    f.write("FIX 0\n")
    for n1, n2, dx, dy, dt in noisy_edges:
        info = INFO_LOOP if (n1 == 7 and n2 == 0) else INFO_ODOM
        f.write("EDGE_SE2 %d %d %.10f %.10f %.10f %s\n" % (n1, n2, dx, dy, dt, info))
    # Outlier edges with grossly wrong measurements
    f.write("EDGE_SE2 1 5 1.0000000000 3.0000000000 0.5000000000 %s\n" % INFO_OUTLIER)
    f.write("EDGE_SE2 2 6 -2.0000000000 1.0000000000 -1.0000000000 %s\n" % INFO_OUTLIER)

# --- Ground truth poses for evaluation ---
with open("/app/graphs/ground_truth.txt", "w") as f:
    for i, (x, y, t) in enumerate(ground_truth):
        f.write("%d %.10f %.10f %.10f\n" % (i, x, y, t))

print("Generated pose graph files successfully.")

#!/usr/bin/env python3
"""Generate deterministic pose graph data in SQLite format with binary BLOBs."""
import sqlite3
import struct
import math
import random

random.seed(42)


def normalize_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a <= -math.pi:
        a += 2 * math.pi
    return a


# Ground truth: out-and-back trajectory along x-axis
# Forward leg (east): nodes 0-9
# Turnaround: node 9->10 (pure rotation)
# Return leg (west): nodes 10-19
GT = []
for i in range(10):
    GT.append((i * 5.0, 0.0, 0.0))
GT.append((45.0, 0.0, math.pi))
for i in range(1, 10):
    GT.append(((9 - i) * 5.0, 0.0, math.pi))

N = len(GT)


def relative_transform(pose_i, pose_j):
    xi, yi, ti = pose_i
    xj, yj, tj = pose_j
    ci, si = math.cos(ti), math.sin(ti)
    dx, dy = xj - xi, yj - yi
    local_dx = ci * dx + si * dy
    local_dy = -si * dx + ci * dy
    dtheta = normalize_angle(tj - ti)
    return (local_dx, local_dy, dtheta)


# Noise parameters
odom_sigma_t = 0.3
odom_sigma_r = 0.03
lc_sigma_t = 0.1
lc_sigma_r = 0.01

# Information matrices (inverse covariance, upper triangle of 3x3 symmetric)
odom_info = [11.0, 0.0, 0.0, 11.0, 0.0, 1100.0]
lc_info = [100.0, 0.0, 0.0, 100.0, 0.0, 10000.0]

# Generate noisy odometry
noisy_odom = []
for k in range(N - 1):
    true_z = relative_transform(GT[k], GT[k + 1])
    noisy_z = (
        true_z[0] + random.gauss(0, odom_sigma_t),
        true_z[1] + random.gauss(0, odom_sigma_t),
        normalize_angle(true_z[2] + random.gauss(0, odom_sigma_r)),
    )
    noisy_odom.append(noisy_z)

# Dead-reckoning initial poses
init_poses = [(0.0, 0.0, 0.0)]
for k in range(N - 1):
    px, py, pt = init_poses[-1]
    dx, dy, dt = noisy_odom[k]
    cp, sp = math.cos(pt), math.sin(pt)
    nx = px + cp * dx - sp * dy
    ny = py + sp * dx + cp * dy
    nt = normalize_angle(pt + dt)
    init_poses.append((nx, ny, nt))

# Build edges
edges = []

# Odometry edges
for k in range(N - 1):
    edges.append({
        "from_id": k, "to_id": k + 1,
        "dx": round(noisy_odom[k][0], 6),
        "dy": round(noisy_odom[k][1], 6),
        "dtheta": round(noisy_odom[k][2], 6),
        "information": odom_info,
        "type": "odometry",
    })

# True loop closures (return nodes matched to forward nodes)
true_lc_pairs = [(19, 0), (17, 2), (15, 4), (13, 6), (11, 8)]
for fi, ti in true_lc_pairs:
    true_z = relative_transform(GT[fi], GT[ti])
    edges.append({
        "from_id": fi, "to_id": ti,
        "dx": round(true_z[0] + random.gauss(0, lc_sigma_t), 6),
        "dy": round(true_z[1] + random.gauss(0, lc_sigma_t), 6),
        "dtheta": round(
            normalize_angle(true_z[2] + random.gauss(0, lc_sigma_r)), 6
        ),
        "information": lc_info,
        "type": "loop_closure",
    })

# Outlier loop closure 1: node 14->1
# Node 14 at (25, 0, pi), node 1 at (5, 0, 0) -- 20m apart
# Fake measurement claims they overlap
edges.append({
    "from_id": 14, "to_id": 1,
    "dx": 0.5, "dy": 0.2,
    "dtheta": round(normalize_angle(math.pi + 0.05), 6),
    "information": lc_info,
    "type": "loop_closure",
})

# Outlier loop closure 2: node 16->8
# Node 16 at (15, 0, pi), node 8 at (40, 0, 0) -- 25m apart
# Fake measurement claims they overlap
edges.append({
    "from_id": 16, "to_id": 8,
    "dx": 0.3, "dy": -0.1,
    "dtheta": round(normalize_angle(math.pi + 0.1), 6),
    "information": lc_info,
    "type": "loop_closure",
})

# Write to SQLite database
conn = sqlite3.connect('/app/pose_graph.db')
c = conn.cursor()

c.execute('''CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    x REAL NOT NULL,
    y REAL NOT NULL,
    theta REAL NOT NULL
)''')

c.execute('''CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    dx REAL NOT NULL,
    dy REAL NOT NULL,
    dtheta REAL NOT NULL,
    info_matrix BLOB NOT NULL,
    edge_type TEXT NOT NULL,
    FOREIGN KEY (from_id) REFERENCES nodes(id),
    FOREIGN KEY (to_id) REFERENCES nodes(id)
)''')

for k in range(N):
    c.execute('INSERT INTO nodes VALUES (?, ?, ?, ?)',
              (k, round(init_poses[k][0], 6), round(init_poses[k][1], 6),
               round(init_poses[k][2], 6)))

for edge in edges:
    info = edge['information']
    blob = struct.pack('<6d', *info)
    c.execute(
        'INSERT INTO edges (from_id, to_id, dx, dy, dtheta, info_matrix, edge_type) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (edge['from_id'], edge['to_id'], edge['dx'], edge['dy'],
         edge['dtheta'], blob, edge['type']))

conn.commit()
conn.close()
print(f"Generated pose_graph.db: {N} nodes, {len(edges)} edges")

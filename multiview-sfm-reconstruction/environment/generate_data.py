#!/usr/bin/env python3
"""Generate synthetic multi-view SfM dataset with ground truth."""
import numpy as np
import json
import os

np.random.seed(42)

def rot_y(deg):
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

def rot_x(deg):
    r = np.radians(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])

NUM_CAMERAS = 5
NUM_POINTS = 60
NOISE_SIGMA = 0.5
OUTLIER_RATE = 0.10
W, H = 1920, 1080

intrinsics_list = [
    {"camera_id": 0, "fx": 1000.0, "fy": 1000.0, "cx": 960.0, "cy": 540.0},
    {"camera_id": 1, "fx": 1050.0, "fy": 1050.0, "cx": 955.0, "cy": 538.0},
    {"camera_id": 2, "fx": 980.0,  "fy": 980.0,  "cx": 962.0, "cy": 542.0},
    {"camera_id": 3, "fx": 1020.0, "fy": 1020.0, "cx": 958.0, "cy": 541.0},
    {"camera_id": 4, "fx": 1100.0, "fy": 1100.0, "cx": 950.0, "cy": 535.0},
]

# Camera extrinsics: P_cam = R @ P_world + t
gt_R = [
    np.eye(3),
    rot_y(12),
    rot_y(25) @ rot_x(3),
    rot_y(-8),
    rot_y(18) @ rot_x(-4),
]
gt_t = [
    np.array([0.0, 0.0, 0.0]),
    np.array([-0.8, 0.05, 0.15]),
    np.array([-1.6, 0.2, 0.4]),
    np.array([0.6, -0.1, 0.08]),
    np.array([-1.2, 0.35, 0.25]),
]

# 3D points in world coordinates
points_3d = np.column_stack([
    np.random.uniform(-2.5, 2.5, NUM_POINTS),
    np.random.uniform(-2.0, 2.0, NUM_POINTS),
    np.random.uniform(5.0, 12.0, NUM_POINTS),
])

# Generate observations with noise and outliers
observations = []
for ci in range(NUM_CAMERAS):
    cam = intrinsics_list[ci]
    K = np.array([[cam["fx"], 0, cam["cx"]],
                  [0, cam["fy"], cam["cy"]],
                  [0, 0, 1]])
    R, t = gt_R[ci], gt_t[ci]

    for pi in range(NUM_POINTS):
        P_cam = R @ points_3d[pi] + t
        if P_cam[2] < 0.5:
            continue
        proj = K @ P_cam
        u, v = proj[0] / proj[2], proj[1] / proj[2]
        margin = 50
        if margin <= u <= W - margin and margin <= v <= H - margin:
            if np.random.random() < OUTLIER_RATE:
                u_obs = float(np.random.uniform(margin, W - margin))
                v_obs = float(np.random.uniform(margin, H - margin))
            else:
                u_obs = float(u + np.random.normal(0, NOISE_SIGMA))
                v_obs = float(v + np.random.normal(0, NOISE_SIGMA))
            observations.append({
                "camera_id": ci,
                "point_id": int(pi),
                "u": round(u_obs, 2),
                "v": round(v_obs, 2)
            })

# Save observation data (visible to agent)
os.makedirs("/app/data", exist_ok=True)
with open("/app/data/intrinsics.json", "w") as f:
    json.dump({
        "image_width": W,
        "image_height": H,
        "cameras": intrinsics_list
    }, f, indent=2)

with open("/app/data/observations.json", "w") as f:
    json.dump({
        "num_cameras": NUM_CAMERAS,
        "num_points": NUM_POINTS,
        "observations": observations
    }, f, indent=2)

# Save ground truth (for test verification only)
os.makedirs("/var/lib/mvtb_gt", exist_ok=True)
gt_data = {
    "cameras": [
        {"camera_id": i, "R": gt_R[i].tolist(), "t": gt_t[i].tolist()}
        for i in range(NUM_CAMERAS)
    ],
    "points_3d": points_3d.tolist()
}
with open("/var/lib/mvtb_gt/ground_truth.json", "w") as f:
    json.dump(gt_data, f)

print(f"Generated {len(observations)} observations across {NUM_CAMERAS} cameras and {NUM_POINTS} points")

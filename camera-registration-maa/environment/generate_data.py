#!/usr/bin/env python3
"""Generate synthetic camera pose data in COLMAP text format with SQLite metadata."""
import numpy as np
import os
import json
import sqlite3

np.random.seed(42)


def random_rotation():
    A = np.random.randn(3, 3)
    Q, R = np.linalg.qr(A)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def axis_angle_to_rotation(axis, angle):
    axis = np.array(axis, dtype=float)
    norm = np.linalg.norm(axis)
    if norm < 1e-10:
        return np.eye(3)
    axis = axis / norm
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def rotation_to_quaternion(R):
    """Convert 3x3 rotation matrix to unit quaternion (w, x, y, z)."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    norm = np.sqrt(w * w + x * x + y * y + z * z)
    return w / norm, x / norm, y / norm, z / norm


def write_colmap_cameras(path, n_cameras):
    """Write COLMAP cameras.txt with one PINHOLE camera per image."""
    with open(path, 'w') as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        f.write(f"# Number of cameras: {n_cameras}\n")
        for i in range(1, n_cameras + 1):
            f.write(f"{i} PINHOLE 1920 1080 1500.0 1500.0 960.0 540.0\n")


def write_colmap_images(path, rotations, translations, image_names):
    """Write COLMAP images.txt with two lines per image."""
    n = len(rotations)
    with open(path, 'w') as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        f.write(f"# Number of images: {n}\n")
        for i, (R, T, name) in enumerate(zip(rotations, translations,
                                              image_names)):
            qw, qx, qy, qz = rotation_to_quaternion(R)
            f.write(f"{i + 1} {qw:.10f} {qx:.10f} {qy:.10f} {qz:.10f} "
                    f"{T[0]:.10f} {T[1]:.10f} {T[2]:.10f} {i + 1} {name}\n")
            # Write synthetic POINTS2D observations
            n_obs = np.random.randint(10, 50)
            obs = []
            for _ in range(n_obs):
                px = np.random.uniform(0, 1920)
                py = np.random.uniform(0, 1080)
                pid = np.random.choice([-1] + list(range(200)))
                obs.append(f"{px:.2f} {py:.2f} {pid}")
            f.write(" ".join(obs) + "\n")


scenes = {"fountain": 12, "temple": 10, "bridge": 15, "tower": 8}

methods_config = {
    "method_a": {
        "pos_noise": 0.005, "rot_noise": 0.001, "outlier_frac": 0.0,
        "scale": 1.5, "axis": [0.1, 0.3, 0.9], "angle": 0.3,
        "trans": [1.0, -0.5, 2.0]
    },
    "method_b": {
        "pos_noise": 0.05, "rot_noise": 0.01, "outlier_frac": 0.15,
        "scale": 0.8, "axis": [0.5, 0.5, 0.7], "angle": -0.5,
        "trans": [-2.0, 1.0, 0.5]
    },
    "method_c": {
        "pos_noise": 0.15, "rot_noise": 0.05, "outlier_frac": 0.35,
        "scale": 2.0, "axis": [0.9, 0.1, 0.4], "angle": 1.2,
        "trans": [0.5, 3.0, -1.0]
    },
}

thresholds = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]

os.makedirs("/app/data", exist_ok=True)

# --- SQLite metadata database ---
db_path = "/app/data/metadata.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""CREATE TABLE eval_config (
    key TEXT PRIMARY KEY,
    value TEXT
)""")
cur.execute("INSERT INTO eval_config VALUES (?, ?)",
            ("thresholds", json.dumps(thresholds)))

cur.execute("""CREATE TABLE reconstructions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_name TEXT,
    scene_name TEXT,
    model_dir TEXT,
    is_ground_truth INTEGER DEFAULT 0
)""")

# --- Generate data ---
for scene_name, n_cameras in scenes.items():
    gt_dir = os.path.join("/app/data", "gt", scene_name)
    os.makedirs(gt_dir, exist_ok=True)

    gt_R_list, gt_T_list = [], []
    image_names = [f"img_{i:04d}.jpg" for i in range(n_cameras)]

    for i in range(n_cameras):
        R = random_rotation()
        theta = np.random.uniform(0, 2 * np.pi)
        phi = np.random.uniform(0.3, np.pi / 2)
        r = np.random.uniform(3, 8)
        pos = np.array([r * np.sin(phi) * np.cos(theta),
                        r * np.sin(phi) * np.sin(theta),
                        r * np.cos(phi)])
        T = -R @ pos
        gt_R_list.append(R)
        gt_T_list.append(T)

    gt_R = np.array(gt_R_list)
    gt_T = np.array(gt_T_list)

    write_colmap_cameras(os.path.join(gt_dir, "cameras.txt"), n_cameras)
    write_colmap_images(os.path.join(gt_dir, "images.txt"),
                        gt_R, gt_T, image_names)

    cur.execute(
        "INSERT INTO reconstructions "
        "(method_name, scene_name, model_dir, is_ground_truth) "
        "VALUES (?, ?, ?, ?)",
        ("ground_truth", scene_name, f"gt/{scene_name}", 1))

    gt_centers = np.array([-R.T @ T for R, T in zip(gt_R, gt_T)])

    for method_name, cfg in methods_config.items():
        method_dir = os.path.join("/app/data", method_name, scene_name)
        os.makedirs(method_dir, exist_ok=True)

        s = cfg["scale"]
        R_sim = axis_angle_to_rotation(cfg["axis"], cfg["angle"])
        t_vec = np.array(cfg["trans"])

        pred_R_list, pred_T_list = [], []

        for i in range(n_cameras):
            C_pred = s * R_sim @ gt_centers[i] + t_vec

            if np.random.random() < cfg["outlier_frac"]:
                C_pred += np.random.randn(3) * 2.0
            else:
                C_pred += np.random.randn(3) * cfg["pos_noise"]

            small = np.random.randn(3) * cfg["rot_noise"]
            norm_s = np.linalg.norm(small)
            if norm_s > 1e-10:
                R_noise = axis_angle_to_rotation(small / norm_s, norm_s)
            else:
                R_noise = np.eye(3)
            R_pred = R_noise @ R_sim @ gt_R[i]
            T_pred = -R_pred @ C_pred

            pred_R_list.append(R_pred)
            pred_T_list.append(T_pred)

        pred_R = np.array(pred_R_list)
        pred_T = np.array(pred_T_list)

        write_colmap_cameras(os.path.join(method_dir, "cameras.txt"),
                             n_cameras)
        write_colmap_images(os.path.join(method_dir, "images.txt"),
                            pred_R, pred_T, image_names)

        cur.execute(
            "INSERT INTO reconstructions "
            "(method_name, scene_name, model_dir, is_ground_truth) "
            "VALUES (?, ?, ?, ?)",
            (method_name, scene_name, f"{method_name}/{scene_name}", 0))

conn.commit()
conn.close()

print("Data generated successfully.")
print(f"SQLite database: {db_path}")
print(f"COLMAP text models: {len(scenes)} scenes x "
      f"{len(methods_config)} methods + ground truth")

#!/usr/bin/env python3

"""
Synthesize a COLMAP SQLite database from text-format sparse reconstruction
and produce a geometric analysis report.
"""

import json
import os
import re
import sqlite3
import struct
from collections import defaultdict

import numpy as np

SPARSE_DIR = "/app/sparse"
DB_PATH = "/app/database.db"
REPORT_PATH = "/app/report.json"

# COLMAP camera model name -> (model_id, num_params)
CAMERA_MODELS = {
    "SIMPLE_PINHOLE": (0, 3),
    "PINHOLE": (1, 4),
    "SIMPLE_RADIAL": (2, 4),
    "RADIAL": (3, 5),
    "OPENCV": (4, 8),
    "OPENCV_FISHEYE": (5, 8),
    "FULL_OPENCV": (6, 12),
    "FOV": (7, 5),
    "SIMPLE_RADIAL_FISHEYE": (8, 4),
    "RADIAL_FISHEYE": (9, 5),
    "THIN_PRISM_FISHEYE": (10, 12),
    "RAD_TAN_THIN_PRISM_FISHEYE": (11, 16),
    "SIMPLE_DIVISION": (12, 4),
    "DIVISION": (13, 5),
    "SIMPLE_FISHEYE": (14, 3),
    "FISHEYE": (15, 4),
    "EUCM": (16, 6),
}


def parse_cameras(path):
    """Parse cameras.txt -> dict of camera_id -> {model, model_id, width, height, params}"""
    cameras = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            cam_id = int(parts[0])
            model_name = parts[1]
            width = int(parts[2])
            height = int(parts[3])
            params = [float(x) for x in parts[4:]]
            model_id, expected_n = CAMERA_MODELS[model_name]
            assert len(params) == expected_n, (
                f"Camera {cam_id}: expected {expected_n} params for {model_name}, got {len(params)}"
            )
            cameras[cam_id] = {
                "model_name": model_name,
                "model_id": model_id,
                "width": width,
                "height": height,
                "params": params,
            }
    return cameras


def parse_images(path):
    """Parse images.txt -> dict of image_id -> {name, camera_id, qvec, tvec, keypoints, point3d_ids}"""
    images = {}
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    i = 0
    while i < len(lines):
        # Line 1: IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME
        parts = lines[i].split()
        img_id = int(parts[0])
        qw, qx, qy, qz = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        tx, ty, tz = float(parts[5]), float(parts[6]), float(parts[7])
        cam_id = int(parts[8])
        name = parts[9]

        # Line 2: POINTS2D[] as (X, Y, POINT3D_ID)
        i += 1
        pts_parts = lines[i].split()
        keypoints = []
        point3d_ids = []
        for j in range(0, len(pts_parts), 3):
            x = float(pts_parts[j])
            y = float(pts_parts[j + 1])
            pid = int(pts_parts[j + 2])
            keypoints.append((x, y))
            point3d_ids.append(pid)

        images[img_id] = {
            "name": name,
            "camera_id": cam_id,
            "qvec": (qw, qx, qy, qz),
            "tvec": (tx, ty, tz),
            "keypoints": keypoints,
            "point3d_ids": point3d_ids,
        }
        i += 1

    return images


def parse_points3d(path):
    """Parse points3D.txt -> dict of point3d_id -> {xyz, rgb, error, track}"""
    points = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            pid = int(parts[0])
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            r, g, b = int(parts[4]), int(parts[5]), int(parts[6])
            error = float(parts[7])
            track = []
            for j in range(8, len(parts), 2):
                img_id = int(parts[j])
                pt2d_idx = int(parts[j + 1])
                track.append((img_id, pt2d_idx))
            points[pid] = {
                "xyz": (x, y, z),
                "rgb": (r, g, b),
                "error": error,
                "track": track,
            }
    return points


def quat_to_rotmat(qw, qx, qy, qz):
    """Convert Hamilton-convention quaternion to 3x3 rotation matrix."""
    return np.array([
        [1 - 2*(qy*qy + qz*qz), 2*(qx*qy - qw*qz), 2*(qx*qz + qw*qy)],
        [2*(qx*qy + qw*qz), 1 - 2*(qx*qx + qz*qz), 2*(qy*qz - qw*qx)],
        [2*(qx*qz - qw*qy), 2*(qy*qz + qw*qx), 1 - 2*(qx*qx + qy*qy)],
    ])


def image_ids_to_pair_id(id1, id2):
    """Compute COLMAP pair_id from two image IDs."""
    if id1 > id2:
        return 2147483647 * id2 + id1
    else:
        return 2147483647 * id1 + id2


def create_database(cameras, images, points3d):
    """Create a COLMAP-compatible SQLite database."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create tables
    cur.execute("""
        CREATE TABLE cameras (
            camera_id INTEGER PRIMARY KEY NOT NULL,
            model INTEGER NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            params BLOB,
            prior_focal_length INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE images (
            image_id INTEGER PRIMARY KEY NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            camera_id INTEGER NOT NULL,
            prior_qw REAL,
            prior_qx REAL,
            prior_qy REAL,
            prior_qz REAL,
            prior_tx REAL,
            prior_ty REAL,
            prior_tz REAL
        )
    """)

    cur.execute("""
        CREATE TABLE keypoints (
            image_id INTEGER PRIMARY KEY NOT NULL,
            rows INTEGER NOT NULL,
            cols INTEGER NOT NULL,
            data BLOB
        )
    """)

    cur.execute("""
        CREATE TABLE descriptors (
            image_id INTEGER PRIMARY KEY NOT NULL,
            rows INTEGER NOT NULL,
            cols INTEGER NOT NULL,
            data BLOB
        )
    """)

    cur.execute("""
        CREATE TABLE matches (
            pair_id INTEGER PRIMARY KEY NOT NULL,
            rows INTEGER NOT NULL,
            cols INTEGER NOT NULL,
            data BLOB
        )
    """)

    cur.execute("""
        CREATE TABLE two_view_geometries (
            pair_id INTEGER PRIMARY KEY NOT NULL,
            rows INTEGER NOT NULL,
            cols INTEGER NOT NULL,
            data BLOB,
            config INTEGER NOT NULL DEFAULT 0,
            F BLOB,
            E BLOB,
            H BLOB,
            qvec BLOB,
            tvec BLOB
        )
    """)

    # Populate cameras
    for cam_id, cam in cameras.items():
        params_blob = struct.pack(f"<{len(cam['params'])}d", *cam["params"])
        cur.execute(
            "INSERT INTO cameras (camera_id, model, width, height, params, prior_focal_length) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (cam_id, cam["model_id"], cam["width"], cam["height"], params_blob),
        )

    # Populate images
    for img_id, img in images.items():
        qw, qx, qy, qz = img["qvec"]
        tx, ty, tz = img["tvec"]
        cur.execute(
            "INSERT INTO images (image_id, name, camera_id, prior_qw, prior_qx, prior_qy, "
            "prior_qz, prior_tx, prior_ty, prior_tz) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (img_id, img["name"], img["camera_id"], qw, qx, qy, qz, tx, ty, tz),
        )

    # Populate keypoints
    for img_id, img in images.items():
        kps = img["keypoints"]
        n_rows = len(kps)
        flat = []
        for x, y in kps:
            flat.extend([x, y])
        kp_blob = struct.pack(f"<{len(flat)}f", *flat)
        cur.execute(
            "INSERT INTO keypoints (image_id, rows, cols, data) VALUES (?, ?, 2, ?)",
            (img_id, n_rows, kp_blob),
        )

    # Populate descriptors (placeholder)
    for img_id in images:
        cur.execute(
            "INSERT INTO descriptors (image_id, rows, cols, data) VALUES (?, 0, 128, ?)",
            (img_id, b""),
        )

    # Extract matches from 3D point tracks
    pair_matches = defaultdict(list)  # pair_id -> list of (idx1, idx2)
    for pid, pt in points3d.items():
        track = pt["track"]
        for i in range(len(track)):
            for j in range(i + 1, len(track)):
                img_id1, pt2d_idx1 = track[i]
                img_id2, pt2d_idx2 = track[j]
                if img_id1 < img_id2:
                    pair_id = image_ids_to_pair_id(img_id1, img_id2)
                    pair_matches[pair_id].append((pt2d_idx1, pt2d_idx2))
                else:
                    pair_id = image_ids_to_pair_id(img_id1, img_id2)
                    pair_matches[pair_id].append((pt2d_idx2, pt2d_idx1))

    # Populate matches
    for pair_id, match_list in pair_matches.items():
        n_rows = len(match_list)
        flat = []
        for idx1, idx2 in match_list:
            flat.extend([idx1, idx2])
        match_blob = struct.pack(f"<{len(flat)}I", *flat)
        cur.execute(
            "INSERT INTO matches (pair_id, rows, cols, data) VALUES (?, ?, 2, ?)",
            (pair_id, n_rows, match_blob),
        )

    # Populate two_view_geometries (placeholder)
    for pair_id in pair_matches:
        cur.execute(
            "INSERT INTO two_view_geometries "
            "(pair_id, rows, cols, data, config, F, E, H, qvec, tvec) "
            "VALUES (?, 0, 2, ?, 0, ?, ?, ?, ?, ?)",
            (pair_id, b"", b"", b"", b"", b"", b""),
        )

    conn.commit()
    conn.close()


def generate_report(cameras, images, points3d, pair_matches):
    """Generate the JSON analysis report."""
    report = {}

    # Camera centers
    camera_centers = {}
    for img_id, img in images.items():
        qw, qx, qy, qz = img["qvec"]
        tx, ty, tz = img["tvec"]
        R = quat_to_rotmat(qw, qx, qy, qz)
        T = np.array([tx, ty, tz])
        center = (-R.T @ T).tolist()
        camera_centers[str(img_id)] = center
    report["camera_centers"] = camera_centers

    # Pair matches
    pair_match_counts = {}
    for pair_id, match_list in pair_matches.items():
        pair_match_counts[str(pair_id)] = len(match_list)
    report["pair_matches"] = pair_match_counts

    # Track length histogram
    histogram = defaultdict(int)
    for pid, pt in points3d.items():
        track_len = len(pt["track"])
        histogram[str(track_len)] += 1
    report["track_length_histogram"] = dict(histogram)

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)


def main():
    cameras = parse_cameras(os.path.join(SPARSE_DIR, "cameras.txt"))
    images = parse_images(os.path.join(SPARSE_DIR, "images.txt"))
    points3d = parse_points3d(os.path.join(SPARSE_DIR, "points3D.txt"))

    # Extract matches from tracks (needed for both DB and report)
    pair_matches = defaultdict(list)
    for pid, pt in points3d.items():
        track = pt["track"]
        for i in range(len(track)):
            for j in range(i + 1, len(track)):
                img_id1, pt2d_idx1 = track[i]
                img_id2, pt2d_idx2 = track[j]
                if img_id1 < img_id2:
                    pair_id = image_ids_to_pair_id(img_id1, img_id2)
                    pair_matches[pair_id].append((pt2d_idx1, pt2d_idx2))
                else:
                    pair_id = image_ids_to_pair_id(img_id1, img_id2)
                    pair_matches[pair_id].append((pt2d_idx2, pt2d_idx1))

    create_database(cameras, images, points3d)
    generate_report(cameras, images, points3d, pair_matches)

    print(f"Database created at {DB_PATH}")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()

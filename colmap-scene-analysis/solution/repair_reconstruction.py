#!/usr/bin/env python3
"""Diagnose, repair, and evaluate COLMAP sparse reconstruction for 3DGS."""

import struct
import os
import json
import math
import sqlite3


CAMERA_MODEL_NUM_PARAMS = {
    0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8,
    6: 12, 7: 5, 8: 4, 9: 5, 10: 12,
}


# ---- Binary readers ----

def read_cameras_bin(path):
    cameras = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            cam_id, model_id = struct.unpack("<ii", f.read(8))
            width, height = struct.unpack("<QQ", f.read(16))
            nparams = CAMERA_MODEL_NUM_PARAMS[model_id]
            params = list(struct.unpack(
                "<" + "d" * nparams, f.read(8 * nparams)))
            cameras[cam_id] = {
                "model_id": model_id, "width": width,
                "height": height, "params": params,
            }
    return cameras


def read_images_bin(path):
    images = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            props = struct.unpack("<idddddddi", f.read(64))
            img_id = props[0]
            qvec = list(props[1:5])
            tvec = list(props[5:8])
            camera_id = props[8]
            name = b""
            ch = f.read(1)
            while ch != b"\x00":
                name += ch
                ch = f.read(1)
            name = name.decode("utf-8")
            num_obs = struct.unpack("<Q", f.read(8))[0]
            observations = []
            for _ in range(num_obs):
                x, y, p3d_id = struct.unpack("<ddq", f.read(24))
                observations.append((x, y, p3d_id))
            images[img_id] = {
                "qvec": qvec, "tvec": tvec,
                "camera_id": camera_id, "name": name,
                "observations": observations,
            }
    return images


def read_points3d_bin(path):
    points = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            props = struct.unpack("<QdddBBBd", f.read(43))
            pt_id = props[0]
            xyz = list(props[1:4])
            rgb = list(props[4:7])
            error = props[7]
            track_len = struct.unpack("<Q", f.read(8))[0]
            track = []
            for _ in range(track_len):
                iid, pidx = struct.unpack("<ii", f.read(8))
                track.append((iid, pidx))
            points[pt_id] = {
                "xyz": xyz, "rgb": rgb,
                "error": error, "track": track,
            }
    return points


# ---- Binary writers ----

def write_cameras_bin(cameras, path):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(cameras)))
        for cam_id in sorted(cameras):
            cam = cameras[cam_id]
            f.write(struct.pack("<ii", cam_id, cam["model_id"]))
            f.write(struct.pack("<QQ", cam["width"], cam["height"]))
            for p in cam["params"]:
                f.write(struct.pack("<d", p))


def write_images_bin(images, path):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for img_id in sorted(images):
            img = images[img_id]
            f.write(struct.pack("<i", img_id))
            f.write(struct.pack("<dddd", *img["qvec"]))
            f.write(struct.pack("<ddd", *img["tvec"]))
            f.write(struct.pack("<i", img["camera_id"]))
            for ch in img["name"]:
                f.write(struct.pack("<c", ch.encode("utf-8")))
            f.write(struct.pack("<c", b"\x00"))
            f.write(struct.pack("<Q", len(img["observations"])))
            for x, y, p3d_id in img["observations"]:
                f.write(struct.pack("<ddq", x, y, p3d_id))


def write_points3d_bin(points, path):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(points)))
        for pt_id in sorted(points):
            pt = points[pt_id]
            f.write(struct.pack("<Q", pt_id))
            f.write(struct.pack("<ddd", *pt["xyz"]))
            f.write(struct.pack("<BBB", *pt["rgb"]))
            f.write(struct.pack("<d", pt["error"]))
            f.write(struct.pack("<Q", len(pt["track"])))
            for iid, pidx in pt["track"]:
                f.write(struct.pack("<ii", iid, pidx))


# ---- Geometric helpers ----

def qvec2rotmat(q):
    w, x, y, z = q
    return [[1-2*y*y-2*z*z, 2*x*y-2*w*z, 2*z*x+2*w*y],
            [2*x*y+2*w*z, 1-2*x*x-2*z*z, 2*y*z-2*w*x],
            [2*z*x-2*w*y, 2*y*z+2*w*x, 1-2*x*x-2*y*y]]


def camera_world_position(qvec, tvec):
    """Compute camera world position as -R^T * t."""
    R = qvec2rotmat(qvec)
    Rt = [[R[j][i] for j in range(3)] for i in range(3)]
    return [-sum(Rt[i][j] * tvec[j] for j in range(3)) for i in range(3)]


def max_triangulation_angle(pt_xyz, cam_positions):
    """Compute max pairwise triangulation angle for a 3D point."""
    max_angle = 0.0
    for i in range(len(cam_positions)):
        for j in range(i + 1, len(cam_positions)):
            ray_i = [cam_positions[i][d] - pt_xyz[d] for d in range(3)]
            ray_j = [cam_positions[j][d] - pt_xyz[d] for d in range(3)]
            ni = math.sqrt(sum(x * x for x in ray_i))
            nj = math.sqrt(sum(x * x for x in ray_j))
            if ni < 1e-10 or nj < 1e-10:
                continue
            cos_a = sum(ray_i[d] * ray_j[d] for d in range(3)) / (ni * nj)
            cos_a = max(-1.0, min(1.0, cos_a))
            angle = math.degrees(math.acos(cos_a))
            max_angle = max(max_angle, angle)
    return max_angle


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ---- Main diagnosis and repair ----

def main():
    base = "/app/scene/sparse/0"
    issues = []

    # Read corrupted reconstruction
    cameras = read_cameras_bin(os.path.join(base, "cameras.bin"))
    images = read_images_bin(os.path.join(base, "images.bin"))
    points = read_points3d_bin(os.path.join(base, "points3D.bin"))

    print("Loaded reconstruction: {} cameras, {} images, {} points".format(
        len(cameras), len(images), len(points)))

    # Connect to ground truth database
    conn = sqlite3.connect("/app/scene/database.db")
    cur = conn.cursor()

    # --- Check 1: Camera intrinsics vs database ---
    print("\n--- Checking camera intrinsics against database ---")
    for row in cur.execute(
            "SELECT camera_id, model, width, height, params FROM cameras"):
        cam_id, model, width, height, params_blob = row
        nparams = CAMERA_MODEL_NUM_PARAMS[model]
        db_params = list(struct.unpack(
            "<" + "d" * nparams, params_blob))
        if cam_id in cameras:
            cam = cameras[cam_id]
            wrong = []
            for i in range(len(db_params)):
                denom = max(abs(db_params[i]), 1e-10)
                if abs(cam["params"][i] - db_params[i]) / denom > 0.01:
                    wrong.append(i)
            if wrong:
                desc = ("Camera {} params corrupted at indices {}: "
                        "found {}, expected {}").format(
                    cam_id, wrong,
                    [cam["params"][i] for i in wrong],
                    [db_params[i] for i in wrong])
                print("  ISSUE: " + desc)
                issues.append({
                    "type": "camera_intrinsics",
                    "description": desc,
                    "affected_ids": [cam_id],
                })
                cameras[cam_id]["params"] = db_params

    # --- Check 2: Image camera assignments vs database ---
    print("\n--- Checking camera assignments against database ---")
    db_assignments = {}
    for row in cur.execute("SELECT image_id, camera_id FROM images"):
        db_assignments[row[0]] = row[1]

    for iid in sorted(images.keys()):
        img = images[iid]
        if iid in db_assignments:
            if img["camera_id"] != db_assignments[iid]:
                desc = ("Image {} assigned to camera {} "
                        "but database says {}").format(
                    iid, img["camera_id"], db_assignments[iid])
                print("  ISSUE: " + desc)
                issues.append({
                    "type": "camera_assignment",
                    "description": desc,
                    "affected_ids": [iid],
                })
                images[iid]["camera_id"] = db_assignments[iid]

    conn.close()

    # --- Check 3: Quaternion normalization ---
    print("\n--- Checking quaternion normalization ---")
    for iid in sorted(images.keys()):
        q = images[iid]["qvec"]
        norm = math.sqrt(sum(x * x for x in q))
        if abs(norm - 1.0) > 0.001:
            desc = ("Image {} has denormalized quaternion "
                    "(norm={:.6f})").format(iid, norm)
            print("  ISSUE: " + desc)
            issues.append({
                "type": "quaternion_normalization",
                "description": desc,
                "affected_ids": [iid],
            })
            images[iid]["qvec"] = [x / norm for x in q]

    # --- Check 4: Orphan track references ---
    print("\n--- Checking orphan track references ---")
    valid_image_ids = set(images.keys())
    for pid in sorted(points.keys()):
        pt = points[pid]
        orphans = [e for e in pt["track"]
                   if e[0] not in valid_image_ids]
        if orphans:
            desc = ("Point {} has {} track entries referencing "
                    "non-existent images: {}").format(
                pid, len(orphans), [o[0] for o in orphans])
            print("  ISSUE: " + desc)
            issues.append({
                "type": "orphan_track_reference",
                "description": desc,
                "affected_ids": [pid],
            })
            points[pid]["track"] = [
                e for e in pt["track"]
                if e[0] in valid_image_ids
            ]

    # --- Check 5: Behind-camera track entries ---
    print("\n--- Checking for behind-camera track entries ---")
    behind_camera_count = 0
    for pid in sorted(points.keys()):
        pt = points[pid]
        xyz = pt["xyz"]
        clean_track = []
        behind = []
        for img_id, pidx in pt["track"]:
            if img_id not in images:
                continue
            img = images[img_id]
            R = qvec2rotmat(img["qvec"])
            z_cam = sum(R[2][c] * xyz[c]
                        for c in range(3)) + img["tvec"][2]
            if z_cam > 0:
                clean_track.append((img_id, pidx))
            else:
                behind.append(img_id)
        if behind:
            behind_camera_count += len(behind)
            desc = ("Point {} has {} track entries where point is "
                    "behind camera: images {}").format(
                pid, len(behind), behind)
            print("  ISSUE: " + desc)
            issues.append({
                "type": "behind_camera_track",
                "description": desc,
                "affected_ids": [pid],
            })
            points[pid]["track"] = clean_track

    # --- Write repaired files ---
    out_dir = "/app/repaired"
    os.makedirs(out_dir, exist_ok=True)
    write_cameras_bin(cameras, os.path.join(out_dir, "cameras.bin"))
    write_images_bin(images, os.path.join(out_dir, "images.bin"))
    write_points3d_bin(points, os.path.join(out_dir, "points3D.bin"))

    # --- Write diagnostic report ---
    report = {
        "issues": issues,
        "total_issues": len(issues),
    }
    with open("/app/diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # ============================================================
    # Compute scene normalization and quality metrics
    # ============================================================
    print("\n--- Computing scene normalization (NeRF++ convention) ---")

    # Camera world positions: -R^T * t
    cam_positions = {}
    for iid, img in images.items():
        cam_positions[iid] = camera_world_position(
            img["qvec"], img["tvec"])

    positions = list(cam_positions.values())
    n = len(positions)
    center = [sum(p[i] for p in positions) / n for i in range(3)]

    max_dist = 0.0
    for p in positions:
        dist = math.sqrt(sum(
            (p[i] - center[i]) ** 2 for i in range(3)))
        max_dist = max(max_dist, dist)
    radius = max_dist * 1.1
    translate = [-c for c in center]

    print("  Center: [{:.4f}, {:.4f}, {:.4f}]".format(*center))
    print("  Radius: {:.4f}".format(radius))

    # Quality metrics
    print("\n--- Computing quality metrics ---")
    tri_angles = []
    low_angle_count = 0
    track_lengths = []

    for pid, pt in points.items():
        track_positions = []
        for img_id, _ in pt["track"]:
            if img_id in cam_positions:
                track_positions.append(cam_positions[img_id])
        track_lengths.append(len(pt["track"]))
        if len(track_positions) >= 2:
            max_angle = max_triangulation_angle(
                pt["xyz"], track_positions)
            tri_angles.append(max_angle)
            if max_angle < 2.0:
                low_angle_count += 1
        else:
            tri_angles.append(0.0)

    median_angle = median(tri_angles)
    mean_track = (sum(track_lengths) / len(track_lengths)
                  if track_lengths else 0.0)

    scene_config = {
        "normalization": {
            "center": center,
            "radius": radius,
            "translate": translate,
        },
        "quality_metrics": {
            "num_cameras": len(cameras),
            "num_images": len(images),
            "num_points": len(points),
            "behind_camera_entries_removed": behind_camera_count,
            "points_below_min_triangulation": low_angle_count,
            "median_triangulation_angle_deg": median_angle,
            "mean_track_length": mean_track,
        },
    }

    with open("/app/scene_config.json", "w") as f:
        json.dump(scene_config, f, indent=2)

    print("\n=== Summary ===")
    print("Found {} issues across {} categories".format(
        len(issues),
        len(set(iss["type"] for iss in issues))))
    print("Behind-camera entries removed: {}".format(behind_camera_count))
    print("Points with low triangulation angle: {}".format(low_angle_count))
    print("Median triangulation angle: {:.2f} deg".format(median_angle))
    print("Mean track length: {:.2f}".format(mean_track))
    print("Repaired files written to {}".format(out_dir))


if __name__ == "__main__":
    main()

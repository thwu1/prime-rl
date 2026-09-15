#!/usr/bin/env python3
"""
COLMAP binary reconstruction analyzer.
Parses cameras.bin, images.bin, points3D.bin and computes geometric analysis.
"""

import struct
import os
import json
import math
from collections import defaultdict

# Camera model ID -> (name, num_params)
CAMERA_MODELS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


def read_next(fid, nbytes, fmt, endian="<"):
    data = fid.read(nbytes)
    return struct.unpack(endian + fmt, data)


def qvec2rotmat(q):
    w, x, y, z = q
    return [
        [1 - 2*y*y - 2*z*z, 2*x*y - 2*w*z, 2*z*x + 2*w*y],
        [2*x*y + 2*w*z, 1 - 2*x*x - 2*z*z, 2*y*z - 2*w*x],
        [2*z*x - 2*w*y, 2*y*z + 2*w*x, 1 - 2*x*x - 2*y*y],
    ]


def mat_vec(M, v):
    return [sum(M[i][j] * v[j] for j in range(3)) for i in range(3)]


def mat_transpose(M):
    return [[M[j][i] for j in range(3)] for i in range(3)]


def vec_sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def vec_dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def vec_norm(v):
    return math.sqrt(sum(x * x for x in v))


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def read_cameras_bin(path):
    cameras = {}
    with open(path, "rb") as f:
        num = read_next(f, 8, "Q")[0]
        for _ in range(num):
            props = read_next(f, 24, "iiQQ")
            cam_id, model_id, width, height = props
            model_name, num_params = CAMERA_MODELS[model_id]
            params = list(read_next(f, 8 * num_params, "d" * num_params))
            cameras[cam_id] = {
                "model_id": model_id,
                "model_name": model_name,
                "width": width,
                "height": height,
                "params": params,
            }
    return cameras


def read_images_bin(path):
    images = {}
    with open(path, "rb") as f:
        num = read_next(f, 8, "Q")[0]
        for _ in range(num):
            props = read_next(f, 64, "idddddddi")
            img_id = props[0]
            qvec = list(props[1:5])
            tvec = list(props[5:8])
            camera_id = props[8]
            name = ""
            ch = read_next(f, 1, "c")[0]
            while ch != b"\x00":
                name += ch.decode("utf-8")
                ch = read_next(f, 1, "c")[0]
            num_pts2d = read_next(f, 8, "Q")[0]
            obs = []
            if num_pts2d > 0:
                raw = read_next(f, 24 * num_pts2d, "ddq" * num_pts2d)
                for k in range(num_pts2d):
                    obs.append((raw[3*k], raw[3*k+1], raw[3*k+2]))
            # Compute world position
            R = qvec2rotmat(qvec)
            Rt = mat_transpose(R)
            world_pos = [-sum(Rt[i][j] * tvec[j] for j in range(3)) for i in range(3)]
            images[img_id] = {
                "qvec": qvec,
                "tvec": tvec,
                "camera_id": camera_id,
                "name": name,
                "num_obs": num_pts2d,
                "world_pos": world_pos,
                "R": R,
            }
    return images


def read_points3d_bin(path):
    points = {}
    with open(path, "rb") as f:
        num = read_next(f, 8, "Q")[0]
        for _ in range(num):
            props = read_next(f, 43, "QdddBBBd")
            pt_id = props[0]
            xyz = list(props[1:4])
            rgb = list(props[4:7])
            error = props[7]
            track_len = read_next(f, 8, "Q")[0]
            track = []
            if track_len > 0:
                raw = read_next(f, 8 * track_len, "ii" * track_len)
                for k in range(track_len):
                    track.append((raw[2*k], raw[2*k+1]))
            points[pt_id] = {
                "xyz": xyz,
                "rgb": rgb,
                "error": error,
                "track": track,
                "image_ids": [t[0] for t in track],
            }
    return points


def analyze(base_dir):
    cam_path = os.path.join(base_dir, "cameras.bin")
    img_path = os.path.join(base_dir, "images.bin")
    pts_path = os.path.join(base_dir, "points3D.bin")

    cameras = read_cameras_bin(cam_path)
    images = read_images_bin(img_path)
    points3d = read_points3d_bin(pts_path)

    num_cameras = len(cameras)
    num_images = len(images)
    num_points3d = len(points3d)

    # Camera models used
    model_names_used = set()
    for img in images.values():
        cam = cameras[img["camera_id"]]
        model_names_used.add(cam["model_name"])
    camera_models = sorted(model_names_used)

    # Scene center and radius
    positions = [img["world_pos"] for img in images.values()]
    center = [sum(p[d] for p in positions) / len(positions) for d in range(3)]
    radius = max(vec_norm(vec_sub(p, center)) for p in positions)

    # Mean track length
    track_lengths = [len(pt["image_ids"]) for pt in points3d.values()]
    mean_track_length = sum(track_lengths) / len(track_lengths)

    # Median reprojection error
    errors = [pt["error"] for pt in points3d.values()]
    median_reproj_error = median(errors)

    # Mean observations per image
    obs_counts = [img["num_obs"] for img in images.values()]
    mean_obs = sum(obs_counts) / len(obs_counts)

    # Covisibility pairs (threshold = 10)
    covis = defaultdict(int)
    for pt in points3d.values():
        imgs = pt["image_ids"]
        for i in range(len(imgs)):
            for j in range(i + 1, len(imgs)):
                pair = (min(imgs[i], imgs[j]), max(imgs[i], imgs[j]))
                covis[pair] += 1
    covisibility_pairs = sum(1 for v in covis.values() if v >= 10)

    # Triangulation angles
    tri_angles = []
    for pt in points3d.values():
        xyz = pt["xyz"]
        cam_positions = [images[iid]["world_pos"] for iid in pt["image_ids"]]
        max_angle = 0.0
        for i in range(len(cam_positions)):
            for j in range(i + 1, len(cam_positions)):
                ray_i = vec_sub(cam_positions[i], xyz)
                ray_j = vec_sub(cam_positions[j], xyz)
                ni = vec_norm(ray_i)
                nj = vec_norm(ray_j)
                if ni < 1e-10 or nj < 1e-10:
                    continue
                cos_a = max(-1.0, min(1.0, vec_dot(ray_i, ray_j) / (ni * nj)))
                angle = math.degrees(math.acos(cos_a))
                max_angle = max(max_angle, angle)
        tri_angles.append(max_angle)
    median_tri_angle = median(tri_angles)

    # Points behind cameras
    pbc = 0
    for pt in points3d.values():
        xyz = pt["xyz"]
        for img_id, img in images.items():
            R = img["R"]
            t = img["tvec"]
            z_cam = sum(R[2][c] * xyz[c] for c in range(3)) + t[2]
            if z_cam <= 0:
                pbc += 1

    # Baseline-to-depth ratios
    bdr_vals = []
    for pt in points3d.values():
        xyz = pt["xyz"]
        cam_positions = [images[iid]["world_pos"] for iid in pt["image_ids"]]
        max_bdr = 0.0
        for i in range(len(cam_positions)):
            for j in range(i + 1, len(cam_positions)):
                baseline = vec_norm(vec_sub(cam_positions[i], cam_positions[j]))
                di = vec_norm(vec_sub(xyz, cam_positions[i]))
                dj = vec_norm(vec_sub(xyz, cam_positions[j]))
                mean_depth = (di + dj) / 2.0
                if mean_depth < 1e-10:
                    continue
                bdr = baseline / mean_depth
                max_bdr = max(max_bdr, bdr)
        bdr_vals.append(max_bdr)
    median_bdr = median(bdr_vals)

    return {
        "num_cameras": num_cameras,
        "num_images": num_images,
        "num_points3d": num_points3d,
        "camera_models": camera_models,
        "scene_center": center,
        "scene_radius": radius,
        "mean_track_length": mean_track_length,
        "median_reprojection_error": median_reproj_error,
        "mean_observations_per_image": mean_obs,
        "covisibility_pairs": covisibility_pairs,
        "median_triangulation_angle_deg": median_tri_angle,
        "points_behind_cameras_count": pbc,
        "median_baseline_depth_ratio": median_bdr,
    }


if __name__ == "__main__":
    result = analyze("/app/scene/sparse/0")
    with open("/app/analysis_report.json", "w") as f:
        json.dump(result, f, indent=2)
    print("Analysis report written to /app/analysis_report.json")
    print(json.dumps(result, indent=2))

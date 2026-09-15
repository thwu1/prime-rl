#!/usr/bin/env python3
"""
Camera Registration mAA Evaluation Pipeline.

Reads COLMAP sparse model text format and SQLite metadata,
computes robust similarity alignment and mAA metric.

"""
import numpy as np
import json
import os
import sqlite3
from itertools import combinations


# ── COLMAP format parsing ────────────────────────────────────────────


def quaternion_to_rotation(w, x, y, z):
    """Convert unit quaternion (w,x,y,z) to 3x3 rotation matrix."""
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z),
         2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
         2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x),
         1 - 2 * (x * x + y * y)],
    ])


def parse_colmap_images(path):
    """
    Parse COLMAP images.txt file.

    Returns (rotations, translations, image_names) where:
      rotations: (N, 3, 3) array of rotation matrices
      translations: (N, 3) array of translation vectors
      image_names: list of N image name strings
    """
    rotations, translations, names = [], [], []
    with open(path) as f:
        lines = f.readlines()

    # Remove comment lines; keep data lines (including POINTS2D lines)
    data = [l.strip() for l in lines
            if l.strip() and not l.strip().startswith('#')]

    # COLMAP images.txt: pairs of lines (image data, then POINTS2D)
    for i in range(0, len(data), 2):
        parts = data[i].split()
        # IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME
        qw, qx, qy, qz = map(float, parts[1:5])
        tx, ty, tz = map(float, parts[5:8])
        name = parts[9]

        R = quaternion_to_rotation(qw, qx, qy, qz)
        rotations.append(R)
        translations.append(np.array([tx, ty, tz]))
        names.append(name)

    return np.array(rotations), np.array(translations), names


# ── Horn's absolute orientation (quaternion formulation) ─────────────


def horn_absolute_orientation(p, q):
    """
    Horn's method for absolute orientation using unit quaternions.
    Finds the optimal similarity transform: q ~ s * R @ p + t

    Parameters
    ----------
    p : ndarray, shape (N, 3) — source 3D points
    q : ndarray, shape (N, 3) — target 3D points

    Returns
    -------
    (s, R, t) or (None, None, None) on failure.
    """
    N = p.shape[0]
    if N < 3:
        return None, None, None

    p_mean = p.mean(axis=0)
    q_mean = q.mean(axis=0)
    pc = p - p_mean
    qc = q - q_mean

    M = pc.T @ qc / N

    Sxx, Sxy, Sxz = M[0, 0], M[0, 1], M[0, 2]
    Syx, Syy, Syz = M[1, 0], M[1, 1], M[1, 2]
    Szx, Szy, Szz = M[2, 0], M[2, 1], M[2, 2]

    N_mat = np.array([
        [Sxx + Syy + Szz, Syz - Szy, Szx - Sxz, Sxy - Syx],
        [Syz - Szy, Sxx - Syy - Szz, Sxy + Syx, Szx + Sxz],
        [Szx - Sxz, Sxy + Syx, -Sxx + Syy - Szz, Syz + Szy],
        [Sxy - Syx, Szx + Sxz, Syz + Szy, -Sxx - Syy + Szz],
    ])

    eigenvalues, eigenvectors = np.linalg.eigh(N_mat)
    quat = eigenvectors[:, -1]
    w, x, y, z = quat

    R = quaternion_to_rotation(w, x, y, z)

    numerator = np.sum(qc * (R @ pc.T).T)
    denominator = np.sum(pc ** 2)
    if denominator < 1e-15:
        return None, None, None
    s = numerator / denominator
    if s <= 0:
        return None, None, None

    t = q_mean - s * R @ p_mean
    return s, R, t


# ── Robust camera registration ──────────────────────────────────────


def register_cameras(pred_centers, gt_centers, threshold):
    """
    RANSAC-like registration via exhaustive triplet search with
    inlier-based refinement.

    Returns the maximum number of cameras registered under any
    similarity transform at the given distance threshold.
    """
    N = len(pred_centers)
    if N < 3:
        return 0

    best_count = 0

    for triplet in combinations(range(N), 3):
        idx = list(triplet)

        s, R, t = horn_absolute_orientation(
            pred_centers[idx], gt_centers[idx])
        if s is None:
            continue

        transformed = s * (R @ pred_centers.T).T + t
        errors = np.linalg.norm(transformed - gt_centers, axis=1)
        inlier_idx = np.where(errors < threshold)[0]

        refine_idx = np.unique(np.concatenate([idx, inlier_idx]))

        if len(refine_idx) >= 3:
            s_r, R_r, t_r = horn_absolute_orientation(
                pred_centers[refine_idx], gt_centers[refine_idx])
            if s_r is not None:
                transformed_r = s_r * (R_r @ pred_centers.T).T + t_r
                errors_r = np.linalg.norm(
                    transformed_r - gt_centers, axis=1)
                count = int(np.sum(errors_r < threshold))
            else:
                count = int(len(inlier_idx))
        else:
            count = int(len(inlier_idx))

        if count > best_count:
            best_count = count

    return best_count


# ── mAA computation ─────────────────────────────────────────────────


def compute_maa(data_dir, methods, scenes, gt_map, thresholds):
    """Compute mAA for each method across all scenes and thresholds."""
    results = {}

    for method in methods:
        accuracies_by_threshold = []

        for threshold in thresholds:
            scene_accuracies = []

            for scene in scenes:
                gt_dir = os.path.join(data_dir, gt_map[scene])
                gt_R, gt_T, gt_names = parse_colmap_images(
                    os.path.join(gt_dir, "images.txt"))

                pred_dir = os.path.join(
                    data_dir, method, scene)
                pred_R, pred_T, pred_names = parse_colmap_images(
                    os.path.join(pred_dir, "images.txt"))

                # Camera world positions: C = -R^T @ T
                gt_centers = np.array(
                    [-R.T @ T for R, T in zip(gt_R, gt_T)])
                pred_centers = np.array(
                    [-R.T @ T for R, T in zip(pred_R, pred_T)])

                # Match cameras by image name
                gt_name_map = {n: i for i, n in enumerate(gt_names)}
                common = [n for n in pred_names if n in gt_name_map]

                if len(common) < 3:
                    scene_accuracies.append(0.0)
                    continue

                gt_idx = [gt_name_map[n] for n in common]
                pred_idx = [pred_names.index(n) for n in common]

                gt_matched = gt_centers[gt_idx]
                pred_matched = pred_centers[pred_idx]

                count = register_cameras(
                    pred_matched, gt_matched, threshold)
                accuracy = count / len(common)
                scene_accuracies.append(accuracy)

            avg_accuracy = float(np.mean(scene_accuracies))
            accuracies_by_threshold.append(avg_accuracy)

        maa = float(
            np.trapz(accuracies_by_threshold, thresholds)
            / (thresholds[-1] - thresholds[0])
        )

        results[method] = {
            "mAA": maa,
            "accuracies": {
                str(t): a
                for t, a in zip(thresholds, accuracies_by_threshold)
            }
        }

    return results


def main():
    # Read evaluation config from SQLite
    conn = sqlite3.connect("/app/data/metadata.db")
    cur = conn.cursor()

    thresholds = json.loads(
        cur.execute(
            "SELECT value FROM eval_config WHERE key='thresholds'"
        ).fetchone()[0]
    )

    # Get ground-truth model directories
    gt_rows = cur.execute(
        "SELECT scene_name, model_dir FROM reconstructions "
        "WHERE is_ground_truth=1"
    ).fetchall()
    gt_map = {row[0]: row[1] for row in gt_rows}

    # Get methods to evaluate
    pred_rows = cur.execute(
        "SELECT DISTINCT method_name FROM reconstructions "
        "WHERE is_ground_truth=0"
    ).fetchall()
    methods = [r[0] for r in pred_rows]

    scenes = list(gt_map.keys())
    conn.close()

    results = compute_maa("/app/data", methods, scenes, gt_map, thresholds)

    ranking = sorted(methods,
                     key=lambda m: results[m]["mAA"], reverse=True)

    output = {
        "thresholds": thresholds,
        "methods": results,
        "ranking": ranking,
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")
    for method in ranking:
        print(f"  {method}: mAA = {results[method]['mAA']:.6f}")


if __name__ == "__main__":
    main()

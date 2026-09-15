"""
Evaluate reconstruction quality on both clean and noisy scenes,
then store results in a SQLite database and export PLY/JSON outputs.

For each scene:
1. Load the scene's 3D points and camera parameters
2. Project points to camera 1's depth map
3. Unproject back to world coordinates
4. Align reconstructed points to clean ground truth
5. Compute quality metrics and per-point classifications
6. Store in SQLite database
7. Export aligned point clouds as binary PLY files
8. Generate JSON evaluation report
"""


import numpy as np
import sqlite3
import json
import struct
import sys
import os

sys.path.insert(0, '/app')

from colmap_io import load_scene, build_extrinsic_from_quat_trans
from geometry_utils import depth_to_world_coords_points, project_points_to_camera
from alignment import (
    estimate_similarity_transform,
    apply_similarity_transform,
    robust_estimate_similarity_transform,
)


def evaluate_scene(scene_dir, clean_dir, use_robust=False):
    """
    Evaluate reconstruction quality for a scene by round-tripping
    3D points through camera 1's depth map.

    Args:
        scene_dir: path to COLMAP text format scene to evaluate
        clean_dir: path to clean ground truth scene
        use_robust: if True, use RANSAC-based robust alignment

    Returns:
        dict with quality metrics, per-point classification data,
        aligned coordinates, colors, residuals, and inlier mask
    """
    # Load the scene to evaluate and the clean ground truth
    cameras, images, points = load_scene(scene_dir)
    _, _, clean_points = load_scene(clean_dir)

    # Get sorted point IDs (common to both scenes)
    point_ids = sorted(points.keys())
    scene_pts = np.array([points[pid]['xyz'] for pid in point_ids])
    colors_all = np.array([points[pid]['rgb'] for pid in point_ids])
    gt_pts = np.array([clean_points[pid]['xyz'] for pid in point_ids])

    # Camera 1 parameters
    img = images[1]
    cam = cameras[img['camera_id']]
    intrinsic = cam['intrinsic']
    H, W = cam['height'], cam['width']
    ext = build_extrinsic_from_quat_trans(img['quat_xyzw'], img['translation'])

    # Project scene points to camera 1
    pixels, depths = project_points_to_camera(scene_pts, ext, intrinsic)

    # Build depth map
    depth_map = np.zeros((H, W), dtype=np.float64)
    valid = []
    for i, pid in enumerate(point_ids):
        u = int(round(pixels[i, 0]))
        v = int(round(pixels[i, 1]))
        if 0 <= u < W and 0 <= v < H and depths[i] > 0:
            depth_map[v, u] = depths[i]
            valid.append((i, pid, u, v))

    # Unproject to world coordinates
    world_rec, _, _ = depth_to_world_coords_points(depth_map, ext, intrinsic)

    # Extract reconstructed and ground truth points at valid locations
    rec_pts = np.array([world_rec[v, u] for _, _, u, v in valid])
    gt_valid = np.array([gt_pts[i] for i, _, _, _ in valid])
    colors_valid = np.array([colors_all[i] for i, _, _, _ in valid])
    valid_ids = [pid for _, pid, _, _ in valid]

    # Align reconstructed to ground truth
    if use_robust:
        s, R, t, inlier_mask = robust_estimate_similarity_transform(
            rec_pts, gt_valid, inlier_threshold=1.0
        )
    else:
        s, R, t = estimate_similarity_transform(rec_pts, gt_valid)
        inlier_mask = np.ones(len(rec_pts), dtype=bool)

    # Compute residuals after alignment
    aligned = s * (R @ rec_pts.T).T + t
    residuals = np.linalg.norm(aligned - gt_valid, axis=1)

    # RMSE on inliers only
    if np.any(inlier_mask):
        rmse = np.sqrt(np.mean(residuals[inlier_mask] ** 2))
    else:
        rmse = float('inf')

    return {
        'num_points': len(rec_pts),
        'num_inliers': int(np.sum(inlier_mask)),
        'inlier_ratio': float(np.sum(inlier_mask)) / len(rec_pts),
        'rmse': float(rmse),
        'scale': float(s),
        'aligned_pts': aligned,
        'colors': colors_valid,
        'residuals': residuals,
        'inlier_mask': inlier_mask,
        'point_data': [
            {
                'point_id': valid_ids[i],
                'gt_x': float(gt_valid[i, 0]),
                'gt_y': float(gt_valid[i, 1]),
                'gt_z': float(gt_valid[i, 2]),
                'rec_x': float(rec_pts[i, 0]),
                'rec_y': float(rec_pts[i, 1]),
                'rec_z': float(rec_pts[i, 2]),
                'residual': float(residuals[i]),
                'is_inlier': int(inlier_mask[i]),
            }
            for i in range(len(rec_pts))
        ],
    }


def write_ply(filepath, aligned_pts, colors, residuals, inlier_mask, inliers_only=False):
    """Write point cloud as binary little-endian PLY file.

    Args:
        filepath: output PLY file path
        aligned_pts: (N, 3) aligned 3D coordinates
        colors: (N, 3) RGB colors as uint8
        residuals: (N,) per-point residuals
        inlier_mask: (N,) boolean inlier mask
        inliers_only: if True, only write inlier points
    """
    if inliers_only:
        mask = inlier_mask.astype(bool)
        pts = aligned_pts[mask]
        cols = colors[mask]
        res = residuals[mask]
        inl = inlier_mask[mask]
    else:
        pts = aligned_pts
        cols = colors
        res = residuals
        inl = inlier_mask

    n = len(pts)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float64 x\n"
        "property float64 y\n"
        "property float64 z\n"
        "property uint8 red\n"
        "property uint8 green\n"
        "property uint8 blue\n"
        "property float64 residual\n"
        "property uint8 is_inlier\n"
        "end_header\n"
    )

    with open(filepath, 'wb') as f:
        f.write(header.encode('ascii'))
        for i in range(n):
            f.write(struct.pack('<ddd',
                                float(pts[i, 0]),
                                float(pts[i, 1]),
                                float(pts[i, 2])))
            f.write(struct.pack('<BBB',
                                int(cols[i, 0]),
                                int(cols[i, 1]),
                                int(cols[i, 2])))
            f.write(struct.pack('<d', float(res[i])))
            f.write(struct.pack('<B', int(inl[i])))


def create_database(clean_results, noisy_results, db_path='/app/results.db'):
    """Create SQLite database with quality metrics and point classifications."""
    # Remove existing database if present
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    # Create tables
    conn.execute("""
        CREATE TABLE quality_metrics (
            scene_name TEXT PRIMARY KEY,
            num_points INTEGER,
            num_inliers INTEGER,
            inlier_ratio REAL,
            rmse REAL,
            scale REAL
        )
    """)

    conn.execute("""
        CREATE TABLE point_classifications (
            scene_name TEXT,
            point_id INTEGER,
            gt_x REAL,
            gt_y REAL,
            gt_z REAL,
            rec_x REAL,
            rec_y REAL,
            rec_z REAL,
            residual REAL,
            is_inlier INTEGER,
            PRIMARY KEY (scene_name, point_id)
        )
    """)

    # Insert data for each scene
    for name, results in [('clean', clean_results), ('noisy', noisy_results)]:
        conn.execute(
            "INSERT INTO quality_metrics VALUES (?, ?, ?, ?, ?, ?)",
            (name, results['num_points'], results['num_inliers'],
             results['inlier_ratio'], results['rmse'], results['scale'])
        )
        for pd in results['point_data']:
            conn.execute(
                "INSERT INTO point_classifications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, pd['point_id'], pd['gt_x'], pd['gt_y'], pd['gt_z'],
                 pd['rec_x'], pd['rec_y'], pd['rec_z'], pd['residual'], pd['is_inlier'])
            )

    conn.commit()
    conn.close()
    print(f"[Created] {db_path}")


def generate_report(clean_results, noisy_results, report_path='/app/output/report.json'):
    """Generate JSON evaluation report with per-scene metrics and point data."""
    def serialize_results(results):
        return {
            'num_points': results['num_points'],
            'num_inliers': results['num_inliers'],
            'inlier_ratio': results['inlier_ratio'],
            'rmse': results['rmse'],
            'scale': results['scale'],
            'point_data': results['point_data'],
        }

    report = {
        'clean': serialize_results(clean_results),
        'noisy': serialize_results(noisy_results),
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"[Created] {report_path}")


if __name__ == "__main__":
    os.makedirs('/app/output', exist_ok=True)

    print("Evaluating clean scene...")
    clean_results = evaluate_scene('/app/data', '/app/data', use_robust=False)
    print(f"  Points: {clean_results['num_points']}, "
          f"Inliers: {clean_results['num_inliers']}, "
          f"RMSE: {clean_results['rmse']:.6f}, "
          f"Scale: {clean_results['scale']:.4f}")

    print("Evaluating noisy scene...")
    noisy_results = evaluate_scene('/app/data_noisy', '/app/data', use_robust=True)
    print(f"  Points: {noisy_results['num_points']}, "
          f"Inliers: {noisy_results['num_inliers']}, "
          f"RMSE: {noisy_results['rmse']:.6f}, "
          f"Scale: {noisy_results['scale']:.4f}")

    print("Creating database...")
    create_database(clean_results, noisy_results)

    print("Exporting PLY files...")
    write_ply('/app/output/clean.ply',
              clean_results['aligned_pts'], clean_results['colors'],
              clean_results['residuals'], clean_results['inlier_mask'],
              inliers_only=False)
    write_ply('/app/output/noisy_inliers.ply',
              noisy_results['aligned_pts'], noisy_results['colors'],
              noisy_results['residuals'], noisy_results['inlier_mask'],
              inliers_only=True)

    print("Generating JSON report...")
    generate_report(clean_results, noisy_results)

    print("\nEvaluation complete.")

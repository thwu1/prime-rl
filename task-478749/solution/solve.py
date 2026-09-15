#!/usr/bin/env python3
"""
Multi-Sensor LIDAR Battery Cell Inspection Pipeline.

Estimates sensor calibration biases from overlapping observations,
fuses corrected multi-sensor data, rejects manufacturing seam artifacts,
and detects/classifies physical defects on cylindrical battery cells.
"""

import numpy as np
import json
import os
import yaml
from sklearn.cluster import DBSCAN


def load_specs(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_scan(filepath):
    return np.load(filepath)['points']


def filter_caps(points, cell_height, margin=0.003):
    """Remove top/bottom cap points by z-coordinate."""
    mask = (points[:, 2] > margin) & (points[:, 2] < cell_height - margin)
    return points[mask]


def fit_circle_algebraic(x, y):
    """Kasa algebraic circle fit."""
    A = np.column_stack([x, y, np.ones_like(x)])
    b = -(x ** 2 + y ** 2)
    result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    cx = -result[0] / 2
    cy = -result[1] / 2
    r_sq = cx ** 2 + cy ** 2 - result[2]
    r = np.sqrt(max(r_sq, 1e-12))
    return cx, cy, r


def fit_circle_robust(x, y, n_iter=10):
    """Iteratively reweighted algebraic circle fit to reject outliers."""
    cx, cy, r = fit_circle_algebraic(x, y)
    for _ in range(n_iter):
        residuals = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - r
        mad = np.median(np.abs(residuals))
        if mad < 1e-10:
            break
        sigma = 1.4826 * mad
        weights = np.exp(-0.5 * (residuals / (2.5 * sigma)) ** 2)
        wx = weights * x
        wy = weights * y
        wxy_sq = weights * (x ** 2 + y ** 2)
        A = np.column_stack([wx, wy, weights])
        b = -wxy_sq
        try:
            result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            break
        cx_new = -result[0] / 2
        cy_new = -result[1] / 2
        r_sq = cx_new ** 2 + cy_new ** 2 - result[2]
        if r_sq > 0:
            cx, cy = cx_new, cy_new
            r = np.sqrt(r_sq)
    return cx, cy, r


def estimate_calibration(cell_height, sensor_ids, num_cells=12):
    """Estimate relative sensor calibration biases from all cell scans.

    For each cell, fits a circle to each sensor's surface points independently.
    The fitted center encodes true_cell_center + sensor_bias. By computing
    pairwise center differences across cells and taking the robust median,
    we isolate the per-sensor bias (constant across cells) from the per-cell
    center offset (varies across cells but cancels in the difference).
    """
    centers = {s: [] for s in sensor_ids}

    for cell_id in range(num_cells):
        cell_centers = {}
        all_present = True
        for s_id in sensor_ids:
            path = f'/app/scans/cell_{cell_id:02d}_{s_id}.npz'
            if not os.path.exists(path):
                all_present = False
                break
            pts = load_scan(path)
            surface = filter_caps(pts, cell_height)
            if len(surface) < 50:
                all_present = False
                break
            cx, cy, _ = fit_circle_robust(surface[:, 0], surface[:, 1])
            cell_centers[s_id] = np.array([cx, cy])

        if all_present:
            for s_id in sensor_ids:
                centers[s_id].append(cell_centers[s_id])

    ref = sensor_ids[0]
    relative_biases = {ref: np.array([0.0, 0.0])}

    for s_id in sensor_ids[1:]:
        diffs = []
        for i in range(len(centers[ref])):
            if i < len(centers[s_id]):
                diffs.append(centers[s_id][i] - centers[ref][i])
        if diffs:
            diffs = np.array(diffs)
            relative_biases[s_id] = np.median(diffs, axis=0)
        else:
            relative_biases[s_id] = np.array([0.0, 0.0])

    return relative_biases


def merge_corrected_scans(cell_id, relative_biases, sensor_ids):
    """Load, correct calibration bias, and merge all sensor scans for a cell."""
    all_points = []
    for s_id in sensor_ids:
        path = f'/app/scans/cell_{cell_id:02d}_{s_id}.npz'
        if not os.path.exists(path):
            continue
        pts = load_scan(path)
        pts[:, 0] -= relative_biases[s_id][0]
        pts[:, 1] -= relative_biases[s_id][1]
        all_points.append(pts)

    if not all_points:
        return np.empty((0, 3))
    return np.vstack(all_points)


def minimum_angular_extent(theta_array):
    """Compute minimum angular arc covering all angles (handles wrapping)."""
    if len(theta_array) < 2:
        return 0.0
    s = np.sort(theta_array)
    gaps = np.diff(s)
    wrap_gap = 2 * np.pi - (s[-1] - s[0])
    max_gap = max(np.max(gaps), wrap_gap)
    return 2 * np.pi - max_gap


def classify_cluster(cluster_pts, cluster_res, cx, cy, cell_radius, cell_height):
    """Classify a defect cluster and compute its centroid.

    Returns None if the cluster is identified as a manufacturing seam.
    """
    z = cluster_pts[:, 2]
    z_extent = z.max() - z.min()
    mean_res = np.mean(cluster_res)

    # Seam rejection: full-height outward feature
    if z_extent > 0.5 * cell_height and mean_res > 0:
        return None

    dx = cluster_pts[:, 0] - cx
    dy = cluster_pts[:, 1] - cy
    theta = np.arctan2(dy, dx)

    theta_extent = minimum_angular_extent(theta)
    arc_extent = theta_extent * cell_radius

    if arc_extent > 1e-6:
        aspect_ratio = z_extent / arc_extent
    else:
        aspect_ratio = float('inf')

    if mean_res < 0:
        if aspect_ratio > 2.5:
            defect_type = 3  # SCRATCH
        else:
            defect_type = 1  # DENT
    else:
        defect_type = 2  # BULGE

    centroid_theta = float(np.arctan2(np.mean(dy), np.mean(dx)))
    centroid_z = float(np.mean(z))

    return {
        'defect_type': int(defect_type),
        'theta': round(centroid_theta, 6),
        'z': round(centroid_z, 6),
    }


def filter_seam_points(defect_pts, defect_res, cx, cy, cell_height):
    """Pre-filter manufacturing seam points from the outlier set.

    The seam is a narrow outward ridge spanning the full cell height.
    We identify it by finding an angular band where positive-residual
    outlier points span most of the cell height, then remove all
    positive outlier points in that band.
    """
    outward = defect_res > 0
    if outward.sum() < 5:
        return np.ones(len(defect_pts), dtype=bool)

    dx_out = defect_pts[outward, 0] - cx
    dy_out = defect_pts[outward, 1] - cy
    theta_out = np.arctan2(dy_out, dx_out)
    z_out = defect_pts[outward, 2]

    # For each outward point, check if nearby outward points span most of height
    best_angle = None
    best_z_extent = 0.0
    search_radius = 0.15  # rad — wide enough for seam, narrow enough to avoid bulges

    for t in theta_out:
        dist = np.abs(np.arctan2(np.sin(theta_out - t), np.cos(theta_out - t)))
        nearby = dist < search_radius
        if nearby.sum() < 5:
            continue
        z_ext = z_out[nearby].max() - z_out[nearby].min()
        if z_ext > best_z_extent:
            best_z_extent = z_ext
            best_angle = t

    if best_angle is None or best_z_extent < 0.5 * cell_height:
        return np.ones(len(defect_pts), dtype=bool)

    # Remove positive-residual points near the seam angle
    theta_all = np.arctan2(defect_pts[:, 1] - cy, defect_pts[:, 0] - cx)
    ang_dist = np.abs(np.arctan2(
        np.sin(theta_all - best_angle), np.cos(theta_all - best_angle)
    ))
    seam_mask = (ang_dist < search_radius) & (defect_res > 0)
    return ~seam_mask


def analyze_cell(merged_pts, cell_radius, cell_height, threshold):
    """Detect and classify defects in merged, calibration-corrected point cloud."""
    surface = filter_caps(merged_pts, cell_height)
    if len(surface) < 50:
        return True, []

    cx, cy, r = fit_circle_robust(surface[:, 0], surface[:, 1])

    dx = surface[:, 0] - cx
    dy = surface[:, 1] - cy
    radii = np.sqrt(dx ** 2 + dy ** 2)
    residuals = radii - r

    defect_mask = np.abs(residuals) > threshold
    defect_pts = surface[defect_mask]
    defect_res = residuals[defect_mask]

    if len(defect_pts) < 5:
        return True, []

    # Pre-filter seam points before clustering
    keep_mask = filter_seam_points(defect_pts, defect_res, cx, cy, cell_height)
    defect_pts = defect_pts[keep_mask]
    defect_res = defect_res[keep_mask]

    if len(defect_pts) < 5:
        return True, []

    d_dx = defect_pts[:, 0] - cx
    d_dy = defect_pts[:, 1] - cy
    theta = np.arctan2(d_dy, d_dx)

    # Rotate angles so the largest angular gap falls at ±π,
    # preventing DBSCAN from splitting clusters that wrap around.
    sorted_theta = np.sort(theta)
    gaps = np.diff(sorted_theta)
    wrap_gap = 2 * np.pi - (sorted_theta[-1] - sorted_theta[0])
    all_gaps = np.append(gaps, wrap_gap)
    k = int(np.argmax(all_gaps))
    if k < len(gaps):
        gap_center = (sorted_theta[k] + sorted_theta[k + 1]) / 2
    else:
        gap_center = (sorted_theta[-1] + sorted_theta[0]) / 2 + np.pi
        if gap_center > np.pi:
            gap_center -= 2 * np.pi

    shifted_theta = (theta - gap_center) % (2 * np.pi) - np.pi
    shifted_arc = shifted_theta * cell_radius

    features = np.column_stack([shifted_arc, defect_pts[:, 2]])
    clustering = DBSCAN(eps=0.008, min_samples=5).fit(features)
    labels = clustering.labels_

    defects = []
    for label_id in sorted(set(labels)):
        if label_id == -1:
            continue
        mask = labels == label_id
        if mask.sum() < 5:
            continue

        result = classify_cluster(
            defect_pts[mask], defect_res[mask],
            cx, cy, cell_radius, cell_height
        )
        if result is not None:
            defects.append(result)

    passed = len(defects) == 0
    return passed, defects


def main():
    specs = load_specs('/app/sensor_config.yaml')
    cell_radius = specs['cell']['nominal_radius_m']
    cell_height = specs['cell']['nominal_height_m']
    threshold = specs['defect_detection']['min_deviation_from_surface_m']
    sensor_ids = specs['sensors']['ids']

    # Step 1: Estimate sensor calibration biases
    relative_biases = estimate_calibration(cell_height, sensor_ids)

    # Step 2: Analyze each cell
    results = {
        'sensor_calibration': {
            'bias_B_minus_A': {
                'dx': round(float(relative_biases['B'][0]), 6),
                'dy': round(float(relative_biases['B'][1]), 6),
            },
            'bias_C_minus_A': {
                'dx': round(float(relative_biases['C'][0]), 6),
                'dy': round(float(relative_biases['C'][1]), 6),
            },
        },
        'cells': [],
    }

    for cell_id in range(12):
        merged = merge_corrected_scans(cell_id, relative_biases, sensor_ids)
        passed, defects = analyze_cell(merged, cell_radius, cell_height, threshold)
        results['cells'].append({
            'cell_id': cell_id,
            'passed': passed,
            'defects': defects,
        })

    with open('/app/inspection_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    n_defective = sum(1 for c in results['cells'] if not c['passed'])
    print(f"Calibration estimated: B-A=({results['sensor_calibration']['bias_B_minus_A']['dx']:.5f}, "
          f"{results['sensor_calibration']['bias_B_minus_A']['dy']:.5f})")
    print(f"Analyzed {len(results['cells'])} cells, {n_defective} defective.")
    print(f"Results written to /app/inspection_results.json")


if __name__ == '__main__':
    main()

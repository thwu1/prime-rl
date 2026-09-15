#!/usr/bin/env python3

"""Corrected geometric evaluation pipeline for 3D mesh comparison.

Fixes four defects in the original evaluate.py and implements two missing metrics:
1. Chamfer Distance: uses squared Euclidean distances (not raw Euclidean)
2. Hausdorff Distance: computes bidirectional max-min (not forward only)
3. Voxelized IoU: tests containment for each mesh independently
4. Composite similarity score: uses correct decreasing normalization k/(d+k)
5. NEW: 95th-percentile Hausdorff Distance (HD95)
6. NEW: Surface Deviation Profile (bidirectional histogram)
"""

import argparse
import json
import os
import numpy as np
from scipy.spatial import cKDTree
import trimesh


def sample_surface(mesh, count, rng):
    """Sample points uniformly from mesh surface using area-weighted selection."""
    triangles = mesh.triangles
    v0, v1, v2 = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    total_area = areas.sum()
    if total_area < 1e-12:
        raise ValueError("Mesh has near-zero total surface area")
    probs = areas / total_area
    tri_idx = rng.choice(len(areas), size=count, p=probs)
    r1 = rng.random(count)
    r2 = rng.random(count)
    sqrt_r1 = np.sqrt(r1)
    u = 1.0 - sqrt_r1
    v = sqrt_r1 * (1.0 - r2)
    w = sqrt_r1 * r2
    points = (u[:, None] * v0[tri_idx]
              + v[:, None] * v1[tri_idx]
              + w[:, None] * v2[tri_idx])
    return points


def compute_chamfer(pts_a, pts_b):
    """Compute bidirectional Chamfer Distance (squared Euclidean)."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)
    cd_fwd = np.mean(dist_a2b ** 2)
    cd_bwd = np.mean(dist_b2a ** 2)
    return float((cd_fwd + cd_bwd) / 2.0)


def compute_hausdorff(pts_a, pts_b):
    """Compute bidirectional Hausdorff Distance (Euclidean)."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)
    return float(max(np.max(dist_a2b), np.max(dist_b2a)))


def compute_hausdorff_95(pts_a, pts_b):
    """Compute 95th-percentile Hausdorff Distance (bidirectional)."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)
    p95_fwd = float(np.percentile(dist_a2b, 95))
    p95_bwd = float(np.percentile(dist_b2a, 95))
    return max(p95_fwd, p95_bwd)


def compute_iou(mesh_a, mesh_b, resolution=32):
    """Compute voxelized IoU between two meshes on a shared grid."""
    min_bound = np.minimum(mesh_a.bounds[0], mesh_b.bounds[0])
    max_bound = np.maximum(mesh_a.bounds[1], mesh_b.bounds[1])
    extent = max_bound - min_bound
    padding = extent * 0.05
    min_bound = min_bound - padding
    max_bound = max_bound + padding
    x = np.linspace(min_bound[0], max_bound[0], resolution)
    y = np.linspace(min_bound[1], max_bound[1], resolution)
    z = np.linspace(min_bound[2], max_bound[2], resolution)
    grid = np.stack(np.meshgrid(x, y, z, indexing='ij'), axis=-1)
    points = grid.reshape(-1, 3)
    inside_a = mesh_a.contains(points)
    inside_b = mesh_b.contains(points)
    n_inter = int(np.sum(inside_a & inside_b))
    n_union = int(np.sum(inside_a | inside_b))
    if n_union == 0:
        return 0.0
    return float(n_inter / n_union)


def compute_deviation_profile(pts_a, pts_b, n_bins=10):
    """Compute bidirectional surface deviation profile."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)
    all_dists = np.concatenate([dist_a2b, dist_b2a])
    d_max = float(np.max(all_dists))
    if d_max < 1e-12:
        return [1.0] + [0.0] * (n_bins - 1)
    bin_edges = np.linspace(0.0, d_max, n_bins + 1)
    counts, _ = np.histogram(all_dists, bins=bin_edges)
    total = counts.sum()
    if total == 0:
        return [1.0] + [0.0] * (n_bins - 1)
    profile = (counts / total).tolist()
    return profile


def compute_similarity_score(cd, hd, hd95, iou, profile):
    """Compute normalized [0,1] composite geometric similarity score."""
    if any(v is None for v in [cd, hd, hd95]) or iou is None or profile is None:
        return None
    if not isinstance(profile, list) or len(profile) < 3:
        return None

    cd_sim = 100.0 / (cd + 100.0)
    hd_sim = 50.0 / (hd + 50.0)
    hd95_sim = 50.0 / (hd95 + 50.0)

    iou_sim = iou
    prof_sim = sum(profile[:3])

    weights = [0.30, 0.15, 0.10, 0.30, 0.15]
    scores = [cd_sim, hd_sim, hd95_sim, iou_sim, prof_sim]
    return float(sum(w * s for w, s in zip(weights, scores)))


def check_valid(mesh):
    """Check mesh validity: watertight, positive volume, no degenerate faces."""
    try:
        if mesh.is_empty:
            return False
        if not mesh.is_watertight:
            return False
        vol = mesh.volume
        if vol is None or vol <= 0:
            return False
        areas = mesh.area_faces
        if np.any(areas < 1e-10):
            return False
        return True
    except Exception:
        return False


N_PROFILE_BINS = 10


def evaluate_pair(ref_path, cand_path, n_samples, voxel_res, seed):
    """Evaluate geometric metrics for one reference-candidate pair."""
    ref = trimesh.load(ref_path, force='mesh')
    cand = trimesh.load(cand_path, force='mesh')
    ref_ok = check_valid(ref)
    cand_ok = check_valid(cand)
    result = {'is_valid_ref': ref_ok, 'is_valid_cand': cand_ok}
    if not ref_ok or not cand_ok:
        result.update({
            'chamfer_distance': None,
            'hausdorff_distance': None,
            'hausdorff_95': None,
            'iou': 0.0,
            'deviation_profile': None,
            'similarity_score': None
        })
        return result
    rng = np.random.default_rng(seed)
    ref_pts = sample_surface(ref, n_samples, rng)
    cand_pts = sample_surface(cand, n_samples, rng)
    result['chamfer_distance'] = compute_chamfer(ref_pts, cand_pts)
    result['hausdorff_distance'] = compute_hausdorff(ref_pts, cand_pts)
    result['hausdorff_95'] = compute_hausdorff_95(ref_pts, cand_pts)
    result['iou'] = compute_iou(ref, cand, voxel_res)
    result['deviation_profile'] = compute_deviation_profile(ref_pts, cand_pts, N_PROFILE_BINS)
    result['similarity_score'] = compute_similarity_score(
        result['chamfer_distance'], result['hausdorff_distance'],
        result['hausdorff_95'], result['iou'], result['deviation_profile']
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Geometric evaluation pipeline for 3D mesh comparison')
    parser.add_argument('--pairs', required=True, help='Path to pairs JSON')
    parser.add_argument('--samples', type=int, default=10000)
    parser.add_argument('--voxel-res', type=int, default=32)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    with open(args.pairs) as f:
        pairs_data = json.load(f)

    models_dir = os.path.dirname(os.path.abspath(args.pairs))
    ref_dir = os.path.join(models_dir, 'references')
    cand_dir = os.path.join(models_dir, 'candidates')

    results = []
    for pair in pairs_data['pairs']:
        ref_path = os.path.join(ref_dir, pair['reference'])
        cand_path = os.path.join(cand_dir, pair['candidate'])
        print(f"Evaluating {pair['id']}: {pair['reference']} vs {pair['candidate']}")
        metrics = evaluate_pair(ref_path, cand_path, args.samples, args.voxel_res, args.seed)
        metrics['pair_id'] = pair['id']
        metrics['reference'] = pair['reference']
        metrics['candidate'] = pair['candidate']
        results.append(metrics)
        print(f"  CD={metrics['chamfer_distance']} HD={metrics['hausdorff_distance']} "
              f"HD95={metrics['hausdorff_95']} IoU={metrics['iou']} "
              f"Score={metrics['similarity_score']}")

    with open(args.output, 'w') as f:
        json.dump({'metrics': results}, f, indent=2)
    print(f"Results written to {args.output}")


if __name__ == '__main__':
    main()

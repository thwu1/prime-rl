#!/usr/bin/env python3

"""Geometric evaluation pipeline for 3D mesh comparison.

Computes bidirectional Chamfer Distance, Hausdorff Distance,
voxelized Intersection-over-Union, and mesh validity detection
for pairs of STL mesh models.
"""

import argparse
import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree
import trimesh


def sample_surface_uniform(mesh, count, rng):
    """Sample points uniformly from mesh surface via area-weighted barycentric coordinates.

    Each triangle is selected with probability proportional to its area.
    Within each triangle, a point is sampled at uniform-random barycentric
    coordinates using the sqrt decomposition method.
    """
    triangles = mesh.triangles  # (N_tri, 3, 3)
    v0 = triangles[:, 0]
    v1 = triangles[:, 1]
    v2 = triangles[:, 2]

    # Triangle areas
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    total_area = areas.sum()

    if total_area < 1e-12:
        raise ValueError("Mesh has near-zero total surface area")

    # Area-weighted triangle selection
    probs = areas / total_area
    tri_idx = rng.choice(len(areas), size=count, p=probs)

    # Uniform barycentric coordinates via sqrt decomposition
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


def chamfer_distance(pts_a, pts_b):
    """Bidirectional Chamfer Distance: mean of squared nearest-neighbor distances."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)

    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)

    cd_fwd = np.mean(dist_a2b ** 2)
    cd_bwd = np.mean(dist_b2a ** 2)

    return float((cd_fwd + cd_bwd) / 2.0)


def hausdorff_distance(pts_a, pts_b):
    """Bidirectional Hausdorff Distance: max over both directions of per-point min-distance."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)

    dist_a2b, _ = tree_b.query(pts_a)
    dist_b2a, _ = tree_a.query(pts_b)

    return float(max(np.max(dist_a2b), np.max(dist_b2a)))


def voxelized_iou(mesh_a, mesh_b, resolution=32):
    """Voxelized IoU on a shared grid using solid containment testing.

    Constructs a shared bounding box with 5% padding, creates an R^3 regular
    grid, classifies each grid point as inside/outside each mesh, and computes
    IoU = |intersection| / |union|.
    """
    # Combined bounding box
    min_bound = np.minimum(mesh_a.bounds[0], mesh_b.bounds[0])
    max_bound = np.maximum(mesh_a.bounds[1], mesh_b.bounds[1])

    # 5% padding
    extent = max_bound - min_bound
    padding = extent * 0.05
    min_bound = min_bound - padding
    max_bound = max_bound + padding

    # Regular grid
    x = np.linspace(min_bound[0], max_bound[0], resolution)
    y = np.linspace(min_bound[1], max_bound[1], resolution)
    z = np.linspace(min_bound[2], max_bound[2], resolution)

    grid = np.stack(np.meshgrid(x, y, z, indexing='ij'), axis=-1)
    points = grid.reshape(-1, 3)

    # Solid containment
    inside_a = mesh_a.contains(points)
    inside_b = mesh_b.contains(points)

    n_intersection = int(np.sum(inside_a & inside_b))
    n_union = int(np.sum(inside_a | inside_b))

    if n_union == 0:
        return 0.0

    return float(n_intersection / n_union)


def check_validity(mesh):
    """Check mesh validity: watertight, positive volume, no degenerate triangles."""
    try:
        if mesh.is_empty:
            return False
        if not mesh.is_watertight:
            return False
        vol = mesh.volume
        if vol is None or vol < 1e-6:
            return False
        face_areas = mesh.area_faces
        if np.any(face_areas < 1e-10):
            return False
        return True
    except Exception:
        return False


def evaluate_pair(ref_path, cand_path, n_samples, voxel_res, seed):
    """Evaluate geometric similarity for a single reference-candidate pair."""
    ref_mesh = trimesh.load(ref_path, force='mesh')
    cand_mesh = trimesh.load(cand_path, force='mesh')

    ref_valid = check_validity(ref_mesh)
    cand_valid = check_validity(cand_mesh)

    result = {
        'is_valid_ref': ref_valid,
        'is_valid_cand': cand_valid,
    }

    # If either mesh is invalid, return null metrics
    if not ref_valid or not cand_valid:
        result['chamfer_distance'] = None
        result['hausdorff_distance'] = None
        result['iou'] = 0.0
        return result

    # Surface sampling with reproducible RNG
    rng = np.random.default_rng(seed)
    ref_pts = sample_surface_uniform(ref_mesh, n_samples, rng)
    cand_pts = sample_surface_uniform(cand_mesh, n_samples, rng)

    # Geometric metrics
    result['chamfer_distance'] = chamfer_distance(ref_pts, cand_pts)
    result['hausdorff_distance'] = hausdorff_distance(ref_pts, cand_pts)
    result['iou'] = voxelized_iou(ref_mesh, cand_mesh, voxel_res)

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Geometric evaluation pipeline for 3D mesh comparison')
    parser.add_argument('--pairs', required=True,
                        help='Path to pairs.json')
    parser.add_argument('--samples', type=int, default=10000,
                        help='Number of surface sample points per mesh')
    parser.add_argument('--voxel-res', type=int, default=32,
                        help='Voxel grid resolution per axis')
    parser.add_argument('--seed', type=int, default=42,
                        help='Random seed for surface sampling')
    parser.add_argument('--output', required=True,
                        help='Output JSON file path')
    args = parser.parse_args()

    with open(args.pairs) as f:
        pairs_data = json.load(f)

    models_dir = os.path.dirname(os.path.abspath(args.pairs))
    ref_dir = os.path.join(models_dir, 'references')
    cand_dir = os.path.join(models_dir, 'candidates')

    all_results = []
    for pair in pairs_data['pairs']:
        pair_id = pair['id']
        ref_file = pair['reference']
        cand_file = pair['candidate']
        ref_path = os.path.join(ref_dir, ref_file)
        cand_path = os.path.join(cand_dir, cand_file)

        print(f"Evaluating {pair_id}: {ref_file} vs {cand_file} ...",
              flush=True)

        try:
            metrics = evaluate_pair(
                ref_path, cand_path, args.samples, args.voxel_res, args.seed)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            metrics = {
                'chamfer_distance': None,
                'hausdorff_distance': None,
                'iou': 0.0,
                'is_valid_ref': False,
                'is_valid_cand': False,
            }

        metrics['pair_id'] = pair_id
        metrics['reference'] = ref_file
        metrics['candidate'] = cand_file
        all_results.append(metrics)

        cd = metrics['chamfer_distance']
        hd = metrics['hausdorff_distance']
        iou = metrics['iou']
        print(f"  CD={cd}  HD={hd}  IoU={iou}  "
              f"valid_ref={metrics['is_valid_ref']}  "
              f"valid_cand={metrics['is_valid_cand']}")

    output = {'metrics': all_results}
    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to {args.output}")


if __name__ == '__main__':
    main()

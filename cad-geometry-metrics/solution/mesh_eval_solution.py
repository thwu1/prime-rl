#!/usr/bin/env python3
"""3D Mesh Geometry Evaluation Pipeline.

Loads binary STL meshes, detects and repairs defects (inverted normals),
computes Chamfer Distance, F1 Score, and Volumetric IoU for mesh pairs.
"""

import json
import os

import numpy as np
from scipy.spatial import cKDTree
import trimesh


# ---------------------------------------------------------------------------
# Mesh loading and repair
# ---------------------------------------------------------------------------

def load_and_repair(stl_path):
    """Load a binary STL mesh, detect defects, repair if possible.

    Returns (mesh, valid, repaired).
    """
    try:
        mesh = trimesh.load(stl_path, file_type="stl", force="mesh", process=False)
    except Exception:
        return None, False, False

    if len(mesh.faces) < 4 or len(mesh.vertices) < 4:
        return None, False, False

    # Binary STL stores separate vertices per triangle; merge coincident
    # vertices so that edge-sharing topology is visible to is_watertight.
    mesh.merge_vertices()

    repaired = False

    # Detect inverted face normals: a watertight mesh with all normals
    # pointing inward will have negative signed volume.
    try:
        if mesh.is_watertight and mesh.volume < 0:
            # Flip face winding order to correct normals
            mesh.faces = mesh.faces[:, [0, 2, 1]]
            repaired = True
    except Exception:
        pass

    return mesh, True, repaired


# ---------------------------------------------------------------------------
# Normalisation and sampling
# ---------------------------------------------------------------------------

def normalize_to_unit_cube(vertices):
    """Centre and scale vertices so the bounding box fits inside [0,1]^3."""
    min_v = vertices.min(axis=0)
    max_v = vertices.max(axis=0)
    extent = (max_v - min_v).max()
    if extent < 1e-12:
        return np.zeros_like(vertices)
    centre = (min_v + max_v) / 2.0
    return (vertices - centre) / extent + 0.5


def sample_surface_points(mesh, n_points=10000, seed=42):
    """Uniformly sample *n_points* from a triangle mesh surface.

    Points are distributed proportionally to triangle area using random
    barycentric coordinates.
    """
    rng = np.random.RandomState(seed)
    verts = mesh.vertices
    faces = mesh.faces

    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]

    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    total = areas.sum()
    if total < 1e-15:
        return verts[: min(n_points, len(verts))]

    probs = areas / total
    tri_idx = rng.choice(len(faces), size=n_points, p=probs)

    r1 = rng.random(n_points)
    r2 = rng.random(n_points)
    s = np.sqrt(r1)

    a = 1.0 - s
    b = s * (1.0 - r2)
    c = s * r2

    return (
        a[:, None] * v0[tri_idx]
        + b[:, None] * v1[tri_idx]
        + c[:, None] * v2[tri_idx]
    )


# ---------------------------------------------------------------------------
# Geometric comparison metrics
# ---------------------------------------------------------------------------

def chamfer_distance(pts_a, pts_b):
    """Bidirectional mean squared nearest-neighbour distance."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    d_a2b, _ = tree_b.query(pts_a)
    d_b2a, _ = tree_a.query(pts_b)
    return float(np.mean(d_a2b ** 2) + np.mean(d_b2a ** 2))


def f1_score(pts_a, pts_b, threshold=0.02):
    """Point-cloud F1 score at distance *threshold*."""
    tree_a = cKDTree(pts_a)
    tree_b = cKDTree(pts_b)
    d_a2b, _ = tree_b.query(pts_a)
    d_b2a, _ = tree_a.query(pts_b)
    precision = float(np.mean(d_a2b < threshold))
    recall = float(np.mean(d_b2a < threshold))
    if precision + recall < 1e-12:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def volumetric_iou(mesh_a, mesh_b, resolution=0.02):
    """Volumetric Intersection-over-Union via grid containment testing."""
    verts_a = normalize_to_unit_cube(mesh_a.vertices.copy())
    verts_b = normalize_to_unit_cube(mesh_b.vertices.copy())
    norm_a = trimesh.Trimesh(vertices=verts_a, faces=mesh_a.faces, process=False)
    norm_b = trimesh.Trimesh(vertices=verts_b, faces=mesh_b.faces, process=False)
    norm_a.fix_normals()
    norm_b.fix_normals()

    margin = resolution / 2.0
    coords = np.arange(margin, 1.0, resolution)
    xx, yy, zz = np.meshgrid(coords, coords, coords, indexing="ij")
    grid = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])

    inside_a = _safe_contains(norm_a, grid)
    inside_b = _safe_contains(norm_b, grid)

    inter = int(np.logical_and(inside_a, inside_b).sum())
    union = int(np.logical_or(inside_a, inside_b).sum())
    return float(inter / union) if union > 0 else 0.0


def _safe_contains(mesh, points):
    """Mesh containment test with voxelisation fallback."""
    try:
        if mesh.is_watertight:
            return mesh.contains(points)
    except Exception:
        pass
    # Fallback: voxelise and check grid alignment
    try:
        vox = mesh.voxelized(pitch=0.02).fill()
        inside = np.zeros(len(points), dtype=bool)
        origin = vox.transform[:3, 3]
        for i, pt in enumerate(points):
            idx = tuple(((pt - origin) / 0.02).astype(int))
            if all(0 <= idx[d] < vox.matrix.shape[d] for d in range(3)):
                inside[i] = vox.matrix[idx]
        return inside
    except Exception:
        return np.zeros(len(points), dtype=bool)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def evaluate_pair(cand_path, ref_path, params):
    """Evaluate one candidate/reference mesh pair."""
    n_pts = params.get("num_sample_points", 10000)
    f1_thresh = params.get("f1_threshold", 0.02)
    vox_res = params.get("voxel_resolution", 0.02)

    result = {
        "candidate": cand_path,
        "reference": ref_path,
        "candidate_valid": False,
        "repaired": False,
        "metrics": {
            "chamfer_distance": None,
            "f1_score": None,
            "volumetric_iou": None,
        },
    }

    cand_mesh, cand_valid, cand_repaired = load_and_repair(
        os.path.join("/app", cand_path)
    )
    if not cand_valid:
        return result

    ref_mesh, ref_valid, _ = load_and_repair(os.path.join("/app", ref_path))
    if not ref_valid:
        return result

    result["candidate_valid"] = True
    result["repaired"] = cand_repaired

    # Sample and normalise
    cand_pts = normalize_to_unit_cube(sample_surface_points(cand_mesh, n_pts))
    ref_pts = normalize_to_unit_cube(sample_surface_points(ref_mesh, n_pts))

    result["metrics"]["chamfer_distance"] = chamfer_distance(cand_pts, ref_pts)
    result["metrics"]["f1_score"] = f1_score(cand_pts, ref_pts, f1_thresh)
    result["metrics"]["volumetric_iou"] = volumetric_iou(
        cand_mesh, ref_mesh, vox_res
    )

    return result


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    params = config.get("parameters", {})
    pair_results = []

    for spec in config["pairs"]:
        print(f"Evaluating: {spec['candidate']} vs {spec['reference']}")
        res = evaluate_pair(spec["candidate"], spec["reference"], params)
        pair_results.append(res)
        if res["candidate_valid"]:
            m = res["metrics"]
            tag = " (repaired)" if res["repaired"] else ""
            print(
                f"  CD={m['chamfer_distance']:.6f}  "
                f"F1={m['f1_score']:.4f}  "
                f"IoU={m['volumetric_iou']:.4f}{tag}"
            )
        else:
            print("  INVALID")

    valid = [p for p in pair_results if p["candidate_valid"]]
    summary = {
        "total_pairs": len(pair_results),
        "valid_candidates": len(valid),
        "repaired_count": sum(1 for p in pair_results if p["repaired"]),
        "mean_chamfer_distance": (
            sum(p["metrics"]["chamfer_distance"] for p in valid) / len(valid)
            if valid
            else 0.0
        ),
        "mean_f1_score": (
            sum(p["metrics"]["f1_score"] for p in valid) / len(valid)
            if valid
            else 0.0
        ),
        "mean_volumetric_iou": (
            sum(p["metrics"]["volumetric_iou"] for p in valid) / len(valid)
            if valid
            else 0.0
        ),
    }

    output = {"pairs": pair_results, "summary": summary}
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults written to /app/results.json")
    print(f"Summary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()

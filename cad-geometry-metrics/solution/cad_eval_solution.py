#!/usr/bin/env python3
"""CAD Geometry Evaluation Pipeline.

Executes CadQuery scripts, compares resulting meshes using Chamfer Distance,
F1 Score, and Volumetric IoU, with automated repair of broken scripts.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from scipy.spatial import cKDTree
import trimesh


# ---------------------------------------------------------------------------
# CadQuery script execution
# ---------------------------------------------------------------------------

def execute_cadquery_script(script_path, work_dir):
    """Execute a CadQuery script in *work_dir* and return (success, stl_path, stderr)."""
    os.makedirs(work_dir, exist_ok=True)
    local_script = os.path.join(work_dir, os.path.basename(script_path))
    shutil.copy2(script_path, local_script)
    proc = subprocess.run(
        [sys.executable, local_script],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=work_dir,
    )
    stl_path = os.path.join(work_dir, "output.stl")
    if proc.returncode == 0 and os.path.exists(stl_path) and os.path.getsize(stl_path) > 0:
        return True, stl_path, proc.stderr
    return False, None, proc.stderr


# ---------------------------------------------------------------------------
# Script repair
# ---------------------------------------------------------------------------

def repair_script(script_path, error_msg):
    """Attempt to repair a broken CadQuery script.  Returns (repaired_code, True) or (None, False)."""
    with open(script_path) as f:
        code = f.read()

    repaired = False

    # Repair 1: threePointArc with collinear / degenerate control points
    if "threePointArc" in code and (
        "GC_MakeArcOfCircle" in error_msg
        or "Standard_Failure" in error_msg
        or "StdFail_NotDone" in error_msg
        or "OCP.Core" in error_msg
    ):
        # Replace .threePointArc((through_x, through_y), (end_x, end_y))
        # with .lineTo(end_x, end_y)
        pattern = r"\.threePointArc\s*\(\s*\([^)]*\)\s*,\s*(\([^)]*\))\s*\)"
        new_code = re.sub(pattern, r".lineTo\1", code, flags=re.DOTALL)
        if new_code != code:
            code = new_code
            repaired = True

    # Repair 2: missing .close() before .extrude()
    if not repaired and "close" not in code and ".extrude(" in code:
        code = re.sub(r"\.extrude\(", ".close().extrude(", code, count=1)
        repaired = True

    if repaired:
        return code, True
    return None, False


# ---------------------------------------------------------------------------
# Mesh processing utilities
# ---------------------------------------------------------------------------

def normalize_to_unit_cube(vertices):
    """Translate and scale vertices so the bounding box fits inside [0,1]³."""
    min_v = vertices.min(axis=0)
    max_v = vertices.max(axis=0)
    extent = (max_v - min_v).max()
    if extent < 1e-12:
        return np.zeros_like(vertices)
    center = (min_v + max_v) / 2.0
    return (vertices - center) / extent + 0.5


def sample_surface_points(mesh, n_points=10000, seed=42):
    """Uniformly sample *n_points* from the surface of a triangle mesh.

    Points are sampled proportionally to triangle area using barycentric
    coordinates, giving a uniform distribution over the surface.
    """
    rng = np.random.RandomState(seed)
    vertices = mesh.vertices
    faces = mesh.faces

    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]

    # Triangle areas
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    total_area = areas.sum()
    if total_area < 1e-15:
        return vertices[:n_points] if len(vertices) >= n_points else vertices

    probs = areas / total_area

    # Sample triangles proportional to area
    tri_idx = rng.choice(len(faces), size=n_points, p=probs)

    # Random barycentric coordinates
    r1 = rng.random(n_points)
    r2 = rng.random(n_points)
    sqrt_r1 = np.sqrt(r1)

    a = 1.0 - sqrt_r1
    b = sqrt_r1 * (1.0 - r2)
    c = sqrt_r1 * r2

    sampled = (
        a[:, None] * v0[tri_idx]
        + b[:, None] * v1[tri_idx]
        + c[:, None] * v2[tri_idx]
    )
    return sampled


# ---------------------------------------------------------------------------
# Geometric comparison metrics
# ---------------------------------------------------------------------------

def chamfer_distance(points_a, points_b):
    """Bidirectional mean squared nearest-neighbor distance."""
    tree_a = cKDTree(points_a)
    tree_b = cKDTree(points_b)
    dist_a2b, _ = tree_b.query(points_a)
    dist_b2a, _ = tree_a.query(points_b)
    return float(np.mean(dist_a2b ** 2) + np.mean(dist_b2a ** 2))


def f1_score(points_a, points_b, threshold=0.02):
    """Point-cloud F1 score: precision and recall at distance *threshold*."""
    tree_a = cKDTree(points_a)
    tree_b = cKDTree(points_b)
    dist_a2b, _ = tree_b.query(points_a)
    dist_b2a, _ = tree_a.query(points_b)
    precision = float(np.mean(dist_a2b < threshold))
    recall = float(np.mean(dist_b2a < threshold))
    if precision + recall < 1e-12:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def volumetric_iou(mesh_a, mesh_b, resolution=0.02):
    """Volumetric Intersection-over-Union via containment testing on a regular grid."""
    # Normalize each mesh independently to [0,1]³
    verts_a = normalize_to_unit_cube(mesh_a.vertices.copy())
    verts_b = normalize_to_unit_cube(mesh_b.vertices.copy())
    norm_a = trimesh.Trimesh(vertices=verts_a, faces=mesh_a.faces, process=False)
    norm_b = trimesh.Trimesh(vertices=verts_b, faces=mesh_b.faces, process=False)

    # Fix normals so containment test works
    norm_a.fix_normals()
    norm_b.fix_normals()

    # Regular grid spanning the unit cube
    margin = resolution / 2.0
    coords = np.arange(margin, 1.0, resolution)
    xx, yy, zz = np.meshgrid(coords, coords, coords, indexing="ij")
    grid_points = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])

    inside_a = _safe_contains(norm_a, grid_points)
    inside_b = _safe_contains(norm_b, grid_points)

    intersection = int(np.logical_and(inside_a, inside_b).sum())
    union = int(np.logical_or(inside_a, inside_b).sum())
    if union == 0:
        return 0.0
    return float(intersection / union)


def _safe_contains(mesh, points):
    """Containment test with fallback for non-watertight meshes."""
    try:
        if mesh.is_watertight:
            return mesh.contains(points)
    except Exception:
        pass
    # Fallback: voxelize with trimesh and fill, then check grid alignment
    try:
        vox = mesh.voxelized(pitch=0.02).fill()
        inside = np.zeros(len(points), dtype=bool)
        for i, pt in enumerate(points):
            idx = tuple(((pt - vox.transform[:3, 3]) / 0.02).astype(int))
            if all(0 <= idx[d] < vox.matrix.shape[d] for d in range(3)):
                inside[i] = vox.matrix[idx]
        return inside
    except Exception:
        return np.zeros(len(points), dtype=bool)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_mesh(stl_path):
    """Load an STL file and return a trimesh object."""
    return trimesh.load(stl_path, file_type="stl", force="mesh")


def evaluate_pair(candidate_path, reference_path, params):
    """Evaluate one candidate/reference pair.  Returns a result dict."""
    n_pts = params.get("num_sample_points", 10000)
    f1_thresh = params.get("f1_threshold", 0.02)
    vox_res = params.get("voxel_resolution", 0.02)

    result = {
        "candidate": candidate_path,
        "reference": reference_path,
        "candidate_valid": False,
        "repaired": False,
        "metrics": {
            "chamfer_distance": None,
            "f1_score": None,
            "volumetric_iou": None,
        },
    }

    # Execute candidate
    with tempfile.TemporaryDirectory() as td_cand:
        ok, cand_stl, err = execute_cadquery_script(
            os.path.join("/app", candidate_path), td_cand
        )

        if not ok:
            # Attempt repair
            repaired_code, did_repair = repair_script(
                os.path.join("/app", candidate_path), err
            )
            if did_repair and repaired_code is not None:
                repaired_path = os.path.join(td_cand, "repaired.py")
                with open(repaired_path, "w") as f:
                    f.write(repaired_code)
                with tempfile.TemporaryDirectory() as td_rep:
                    ok2, cand_stl, err2 = execute_cadquery_script(repaired_path, td_rep)
                    if ok2:
                        result["repaired"] = True
                        result["candidate_valid"] = True
                        cand_mesh = load_mesh(cand_stl)
                    else:
                        return result
            else:
                return result
        else:
            result["candidate_valid"] = True
            cand_mesh = load_mesh(cand_stl)

    # Execute reference
    with tempfile.TemporaryDirectory() as td_ref:
        ok_ref, ref_stl, _ = execute_cadquery_script(
            os.path.join("/app", reference_path), td_ref
        )
        if not ok_ref:
            result["candidate_valid"] = False
            return result
        ref_mesh = load_mesh(ref_stl)

    # Normalize and sample
    cand_pts_raw = sample_surface_points(cand_mesh, n_pts)
    ref_pts_raw = sample_surface_points(ref_mesh, n_pts)

    cand_pts = normalize_to_unit_cube(cand_pts_raw)
    ref_pts = normalize_to_unit_cube(ref_pts_raw)

    # Compute metrics
    result["metrics"]["chamfer_distance"] = chamfer_distance(cand_pts, ref_pts)
    result["metrics"]["f1_score"] = f1_score(cand_pts, ref_pts, f1_thresh)
    result["metrics"]["volumetric_iou"] = volumetric_iou(cand_mesh, ref_mesh, vox_res)

    return result


def main():
    config_path = "/app/config.json"
    with open(config_path) as f:
        config = json.load(f)

    params = config.get("parameters", {})
    pair_results = []

    for pair_spec in config["pairs"]:
        print(f"Evaluating: {pair_spec['candidate']} vs {pair_spec['reference']}")
        res = evaluate_pair(pair_spec["candidate"], pair_spec["reference"], params)
        pair_results.append(res)
        if res["candidate_valid"]:
            m = res["metrics"]
            print(f"  CD={m['chamfer_distance']:.6f}  F1={m['f1_score']:.4f}  IoU={m['volumetric_iou']:.4f}")
        else:
            print("  INVALID (could not produce valid mesh)")

    # Summary
    valid = [p for p in pair_results if p["candidate_valid"]]
    summary = {
        "total_pairs": len(pair_results),
        "valid_candidates": len(valid),
        "repaired_count": sum(1 for p in pair_results if p["repaired"]),
        "mean_chamfer_distance": (
            sum(p["metrics"]["chamfer_distance"] for p in valid) / len(valid)
            if valid else 0.0
        ),
        "mean_f1_score": (
            sum(p["metrics"]["f1_score"] for p in valid) / len(valid)
            if valid else 0.0
        ),
        "mean_volumetric_iou": (
            sum(p["metrics"]["volumetric_iou"] for p in valid) / len(valid)
            if valid else 0.0
        ),
    }

    output = {"pairs": pair_results, "summary": summary}
    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults written to /app/results.json")
    print(f"Summary: {json.dumps(summary, indent=2)}")


if __name__ == "__main__":
    main()

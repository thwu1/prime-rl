#!/usr/bin/env python3
"""CAD Model Evaluation Pipeline for CadQuery-generated 3D models."""

import sys
import json
import subprocess
import tempfile
import os
import re
import numpy as np
from scipy.spatial import KDTree
import trimesh


def normalize_mesh(mesh):
    """Normalize mesh to fit within [0,1]^3 preserving aspect ratio.

    Uses mesh.copy() and in-place vertex modification to preserve
    face normals, winding order, and other mesh properties.
    """
    new_mesh = mesh.copy()
    vertices = new_mesh.vertices.copy()
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    extent = bbox_max - bbox_min
    max_extent = extent.max()
    if max_extent < 1e-12:
        return new_mesh
    center = (bbox_min + bbox_max) / 2.0
    new_mesh.vertices = (vertices - center) / max_extent + 0.5
    return new_mesh


def uniform_surface_sample(mesh, n_points):
    """Area-weighted uniform sampling from triangle mesh surface.

    Samples triangles proportional to their area, then picks a random
    point within each selected triangle using barycentric coordinates.
    """
    triangles = mesh.vertices[mesh.faces]
    v0 = triangles[:, 1] - triangles[:, 0]
    v1 = triangles[:, 2] - triangles[:, 0]
    cross = np.cross(v0, v1)
    areas = 0.5 * np.linalg.norm(cross, axis=1)

    total_area = areas.sum()
    if total_area < 1e-12:
        raise ValueError("Mesh has zero surface area")
    probs = areas / total_area

    rng = np.random.RandomState(42)
    tri_indices = rng.choice(len(mesh.faces), size=n_points, p=probs)

    r1 = rng.rand(n_points)
    r2 = rng.rand(n_points)
    sqrt_r1 = np.sqrt(r1)

    a = 1.0 - sqrt_r1
    b = sqrt_r1 * (1.0 - r2)
    c = sqrt_r1 * r2

    sel = mesh.vertices[mesh.faces[tri_indices]]
    points = (a[:, None] * sel[:, 0]
              + b[:, None] * sel[:, 1]
              + c[:, None] * sel[:, 2])
    return points


def chamfer_distance(points_a, points_b):
    """Chamfer Distance using squared L2 nearest-neighbor distances.

    CD(P,Q) = (1/|P|) sum_{p in P} min_{q in Q} ||p-q||^2
            + (1/|Q|) sum_{q in Q} min_{p in P} ||q-p||^2
    """
    tree_a = KDTree(np.asarray(points_a))
    tree_b = KDTree(np.asarray(points_b))
    d_a2b, _ = tree_b.query(points_a)
    d_b2a, _ = tree_a.query(points_b)
    return float(np.mean(d_a2b ** 2) + np.mean(d_b2a ** 2))


def f1_score_metric(points_a, points_b, threshold=0.02):
    """Threshold-based F1 score between two point clouds.

    Precision = fraction of points_a whose nearest neighbor in points_b
    is within `threshold`.  Recall = symmetric direction.
    F1 = 2 * Precision * Recall / (Precision + Recall).
    """
    tree_a = KDTree(np.asarray(points_a))
    tree_b = KDTree(np.asarray(points_b))
    d_a2b, _ = tree_b.query(points_a)
    d_b2a, _ = tree_a.query(points_b)
    precision = float(np.mean(d_a2b < threshold))
    recall = float(np.mean(d_b2a < threshold))
    if precision + recall < 1e-12:
        return 0.0
    return float(2.0 * precision * recall / (precision + recall))


def _winding_number_contains(mesh, points):
    """Check point containment using the generalized winding number.

    For each query point, sums the signed solid angle subtended by every
    triangular face. A total winding number near +/-1 means the point is
    inside the mesh; near 0 means outside.

    Vectorized over both faces and point batches for performance.
    """
    verts = mesh.vertices.astype(np.float64)
    faces = mesh.faces
    tris = verts[faces]  # (F, 3, 3)
    pts = np.asarray(points, dtype=np.float64)

    n_pts = len(pts)
    n_faces = len(faces)
    winding = np.zeros(n_pts, dtype=np.float64)

    # Batch size chosen to keep memory under ~500MB
    batch_size = max(1, min(4000, 500_000_000 // max(1, n_faces * 3 * 8)))

    # Pre-extract triangle vertices: each is (F, 3)
    t0 = tris[:, 0, :]
    t1 = tris[:, 1, :]
    t2 = tris[:, 2, :]

    for start in range(0, n_pts, batch_size):
        end = min(start + batch_size, n_pts)
        batch = pts[start:end]  # (B, 3)

        # Vectors from each point to each triangle vertex
        # t0 is (F, 3), batch is (B, 3) => result is (F, B, 3)
        a = t0[:, np.newaxis, :] - batch[np.newaxis, :, :]
        b = t1[:, np.newaxis, :] - batch[np.newaxis, :, :]
        c = t2[:, np.newaxis, :] - batch[np.newaxis, :, :]

        # Norms: (F, B)
        na = np.linalg.norm(a, axis=2)
        nb = np.linalg.norm(b, axis=2)
        nc = np.linalg.norm(c, axis=2)

        # Triple product: a . (b x c) => (F, B)
        cross_bc = np.cross(b, c)  # (F, B, 3)
        triple = np.sum(a * cross_bc, axis=2)  # (F, B)

        # Dot products: (F, B)
        ab = np.sum(a * b, axis=2)
        ac = np.sum(a * c, axis=2)
        bc = np.sum(b * c, axis=2)

        # Denominator
        denom = na * nb * nc + ab * nc + ac * nb + bc * na

        # Sum arctan2 over all faces for each point => (B,)
        w = np.sum(np.arctan2(triple, denom), axis=0)
        winding[start:end] = w

    winding /= (4.0 * np.pi)
    return np.abs(winding) > 0.5


def volumetric_iou(mesh_a, mesh_b, resolution=0.02):
    """Volumetric IoU via winding-number containment on a regular grid.

    Creates a grid covering the bounding box of both meshes and checks
    containment using the generalized winding number.
    |V1 intersect V2| / |V1 union V2|.
    """
    bb_min = np.minimum(mesh_a.bounds[0], mesh_b.bounds[0])
    bb_max = np.maximum(mesh_a.bounds[1], mesh_b.bounds[1])

    ranges = [np.arange(bb_min[i], bb_max[i] + resolution * 0.5, resolution)
              for i in range(3)]
    xx, yy, zz = np.meshgrid(ranges[0], ranges[1], ranges[2], indexing='ij')
    grid_points = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])

    inside_a = _winding_number_contains(mesh_a, grid_points)
    inside_b = _winding_number_contains(mesh_b, grid_points)

    intersection = int(np.sum(inside_a & inside_b))
    union = int(np.sum(inside_a | inside_b))

    if union == 0:
        return 0.0
    return float(intersection / union)


def execute_script(script_path, output_stl, timeout=30):
    """Run a CadQuery script in a subprocess, redirecting STL output."""
    with open(script_path, 'r') as f:
        content = f.read()

    # Rewrite the export path so the STL lands where we want it
    modified = re.sub(
        r"cq\.exporters\.export\s*\([^,]+,\s*['\"][^'\"]*['\"]\s*\)",
        f"cq.exporters.export(result, '{output_stl}')",
        content
    )

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, dir='/tmp'
    ) as tmp:
        tmp.write(modified)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            ['python3', tmp_path],
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd='/tmp'
        )
        return proc.returncode == 0 and os.path.exists(output_stl)
    except subprocess.TimeoutExpired:
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def repair_script(script_content):
    """Fix common CadQuery script failures.

    Handles:
    - threePointArc precision errors (near-colinear points at small scale)
    - Missing ``import cadquery`` statements
    - Missing ``cq.exporters.export`` calls
    """
    repaired = script_content

    # --- Fix threePointArc ---
    tpa_pattern = r'\.threePointArc\(\s*\(([^)]+)\)\s*,\s*\(([^)]+)\)\s*\)'

    def _replace_tpa(match):
        end_str = match.group(2)
        return f'.sagittaArc(({end_str}), 0.001)'

    if 'threePointArc' in repaired:
        repaired = re.sub(tpa_pattern, _replace_tpa, repaired)

    # --- Fix missing import ---
    if 'import cadquery' not in repaired and 'from cadquery' not in repaired:
        repaired = 'import cadquery as cq\n' + repaired

    # --- Fix missing export ---
    if 'exporters.export' not in repaired:
        repaired += "\ncq.exporters.export(result, 'output.stl')\n"

    return repaired


def evaluate_pair(ref_stl, cand_stl, n_points=10000,
                  f1_threshold=0.02, voxel_resolution=0.02):
    """Evaluate geometric similarity between two STL files."""
    mesh_ref = trimesh.load(ref_stl)
    mesh_cand = trimesh.load(cand_stl)

    if isinstance(mesh_ref, trimesh.Scene):
        mesh_ref = trimesh.util.concatenate(mesh_ref.dump())
    if isinstance(mesh_cand, trimesh.Scene):
        mesh_cand = trimesh.util.concatenate(mesh_cand.dump())

    norm_ref = normalize_mesh(mesh_ref)
    norm_cand = normalize_mesh(mesh_cand)

    pts_ref = uniform_surface_sample(norm_ref, n_points)
    pts_cand = uniform_surface_sample(norm_cand, n_points)

    cd = chamfer_distance(pts_ref, pts_cand)
    f1 = f1_score_metric(pts_ref, pts_cand, threshold=f1_threshold)
    iou = volumetric_iou(norm_ref, norm_cand, resolution=voxel_resolution)

    return {
        'chamfer_distance': cd,
        'f1_score': f1,
        'volumetric_iou': iou
    }


def run_pipeline(manifest_path, output_path):
    """Run the full evaluation pipeline from a manifest file."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    cfg = manifest.get('config', {})
    n_pts = cfg.get('n_sample_points', 10000)
    f1_thr = cfg.get('f1_threshold', 0.02)
    vox_res = cfg.get('voxel_resolution', 0.02)
    exec_to = cfg.get('execution_timeout', 30)

    results = []
    repair_count = 0
    valid_metrics = []

    for pair in manifest['pairs']:
        entry = {
            'id': pair['id'],
            'reference_executed': False,
            'candidate_executed': False,
            'candidate_repaired': False,
            'metrics': None
        }

        tmp_dir = tempfile.mkdtemp()
        ref_stl = os.path.join(tmp_dir, 'ref.stl')
        cand_stl = os.path.join(tmp_dir, 'cand.stl')

        # Execute reference script
        ref_ok = execute_script(pair['reference'], ref_stl, timeout=exec_to)
        entry['reference_executed'] = ref_ok

        # Execute candidate script
        cand_ok = execute_script(pair['candidate'], cand_stl, timeout=exec_to)

        # Try repair if candidate failed
        if not cand_ok:
            with open(pair['candidate']) as f:
                orig = f.read()
            fixed = repair_script(orig)
            fixed_path = os.path.join(tmp_dir, 'repaired.py')
            with open(fixed_path, 'w') as f:
                f.write(fixed)
            cand_ok = execute_script(fixed_path, cand_stl, timeout=exec_to)
            if cand_ok:
                entry['candidate_repaired'] = True
                repair_count += 1

        entry['candidate_executed'] = cand_ok

        # Compute metrics if both sides succeeded
        if ref_ok and cand_ok:
            try:
                metrics = evaluate_pair(
                    ref_stl, cand_stl, n_pts, f1_thr, vox_res
                )
                entry['metrics'] = metrics
                valid_metrics.append(metrics)
            except Exception as e:
                entry['metrics'] = {'error': str(e)}

        results.append(entry)

    # Build summary
    summary = {
        'total_pairs': len(manifest['pairs']),
        'valid_pairs': len(valid_metrics),
        'repair_count': repair_count
    }
    if valid_metrics:
        summary['mean_chamfer_distance'] = float(
            np.mean([m['chamfer_distance'] for m in valid_metrics])
        )
        summary['mean_f1_score'] = float(
            np.mean([m['f1_score'] for m in valid_metrics])
        )
        summary['mean_volumetric_iou'] = float(
            np.mean([m['volumetric_iou'] for m in valid_metrics])
        )

    output = {'results': results, 'summary': summary}
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    return output


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <manifest.json> <output.json>",
              file=sys.stderr)
        sys.exit(1)
    run_pipeline(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3

"""Mesh geometry alignment and validation pipeline.

Compares a generated STL mesh against a reference STL mesh by performing
point cloud registration (RANSAC + ICP) and computing geometric similarity
metrics. Outputs a JSON validation report to stdout.
"""

import argparse
import copy
import json
import logging
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh
import yaml

# Suppress Open3D info/warning messages from polluting stdout
o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)

logger = logging.getLogger(__name__)


def load_config(config_path):
    """Load validation thresholds from a YAML config file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def clean_mesh(mesh):
    """Clean an Open3D triangle mesh by removing degeneracies."""
    mesh.merge_close_vertices(0.0001)
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_unreferenced_vertices()
    return mesh


def check_watertight(stl_path):
    """Check if a mesh is watertight (manifold, no open edges).

    Returns True if the mesh is watertight, False otherwise.
    """
    mesh = o3d.io.read_triangle_mesh(str(stl_path))
    if not mesh.has_triangles():
        return False
    mesh = clean_mesh(mesh)
    if not mesh.has_triangles():
        return False
    return mesh.is_watertight()


def count_components(stl_path):
    """Count the number of connected components in a mesh."""
    mesh = o3d.io.read_triangle_mesh(str(stl_path))
    if not mesh.has_triangles():
        return 0
    mesh = clean_mesh(mesh)
    if not mesh.has_triangles():
        return 0
    _, cluster_n_triangles, _ = mesh.cluster_connected_triangles()
    return len(cluster_n_triangles)


def compute_volumes(gen_path, ref_path):
    """Compute volumes of both meshes using trimesh.

    Returns (gen_vol, ref_vol, ratio, percent_diff).
    Volume is only meaningful for watertight meshes.
    """
    gen_mesh = trimesh.load(str(gen_path), force="mesh")
    ref_mesh = trimesh.load(str(ref_path), force="mesh")

    gen_vol = float(abs(gen_mesh.volume)) if gen_mesh.is_watertight else None
    ref_vol = float(abs(ref_mesh.volume)) if ref_mesh.is_watertight else None

    if gen_vol is not None and ref_vol is not None and ref_vol > 0:
        ratio = gen_vol / ref_vol
        percent_diff = abs(gen_vol - ref_vol) / ref_vol * 100
    else:
        ratio = None
        percent_diff = None

    return gen_vol, ref_vol, ratio, percent_diff


def preprocess_for_registration(pcd, voxel_size):
    """Downsample point cloud and compute FPFH features for registration.

    Returns (downsampled_pcd, fpfh_features) or (None, None) on failure.
    """
    pcd_down = pcd.voxel_down_sample(voxel_size)
    if not pcd_down.has_points():
        return None, None

    pcd_down.estimate_normals(
        o3d.geometry.KDTreeSearchParamHybrid(
            radius=voxel_size * 2.5, max_nn=35
        )
    )

    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        pcd_down,
        o3d.geometry.KDTreeSearchParamHybrid(
            radius=voxel_size * 5, max_nn=100
        ),
    )

    if fpfh is None or fpfh.data.shape[1] == 0:
        return pcd_down, None

    return pcd_down, fpfh


def align_and_compute_metrics(gen_path, ref_path, config):
    """Align generated mesh to reference using RANSAC+ICP and compute metrics.

    Returns dict with chamfer_distance, hausdorff_95p, hausdorff_99p,
    icp_fitness, and bbox_passed.
    """
    gen_mesh = o3d.io.read_triangle_mesh(str(gen_path))
    ref_mesh = o3d.io.read_triangle_mesh(str(ref_path))

    if not gen_mesh.has_triangles() or not ref_mesh.has_triangles():
        return {
            "chamfer_distance": None,
            "hausdorff_95p": None,
            "hausdorff_99p": None,
            "icp_fitness": None,
            "bbox_passed": False,
        }

    if not gen_mesh.has_vertex_normals():
        gen_mesh.compute_vertex_normals()
    if not ref_mesh.has_vertex_normals():
        ref_mesh.compute_vertex_normals()

    # Sample uniform point clouds from mesh surfaces
    n_points = 50000
    gen_pcd = gen_mesh.sample_points_uniformly(number_of_points=n_points)
    ref_pcd = ref_mesh.sample_points_uniformly(number_of_points=n_points)

    if len(gen_pcd.points) < 100 or len(ref_pcd.points) < 100:
        return {
            "chamfer_distance": None,
            "hausdorff_95p": None,
            "hausdorff_99p": None,
            "icp_fitness": None,
            "bbox_passed": False,
        }

    # --- Global registration with RANSAC ---
    voxel_size = 5.0

    gen_down, fpfh_gen = preprocess_for_registration(gen_pcd, voxel_size)
    ref_down, fpfh_ref = preprocess_for_registration(ref_pcd, voxel_size)

    if (
        gen_down is None
        or fpfh_gen is None
        or ref_down is None
        or fpfh_ref is None
    ):
        return {
            "chamfer_distance": None,
            "hausdorff_95p": None,
            "hausdorff_99p": None,
            "icp_fitness": None,
            "bbox_passed": False,
        }

    distance_thresh = voxel_size * 1.5
    reg = o3d.pipelines.registration

    ransac_result = reg.registration_ransac_based_on_feature_matching(
        source=gen_down,
        target=ref_down,
        source_feature=fpfh_gen,
        target_feature=fpfh_ref,
        mutual_filter=True,
        max_correspondence_distance=distance_thresh,
        estimation_method=reg.TransformationEstimationPointToPoint(False),
        ransac_n=4,
        checkers=[],
        criteria=reg.RANSACConvergenceCriteria(100000, 0.999),
    )

    t_ransac = ransac_result.transformation
    gen_pcd_aligned = copy.deepcopy(gen_pcd).transform(t_ransac)

    # --- ICP refinement ---
    icp_threshold = 1.5
    icp_result = reg.registration_icp(
        source=gen_pcd_aligned,
        target=ref_pcd,
        max_correspondence_distance=icp_threshold,
        init=np.identity(4),
        estimation_method=reg.TransformationEstimationPointToPoint(),
        criteria=reg.ICPConvergenceCriteria(max_iteration=200),
    )

    t_icp = icp_result.transformation
    icp_fitness = float(icp_result.fitness)
    final_transform = t_icp @ t_ransac

    # Apply final alignment to full point cloud
    gen_pcd_final = copy.deepcopy(gen_pcd).transform(final_transform)

    # --- Compute bidirectional distances ---
    dist_gen_to_ref = np.asarray(
        gen_pcd_final.compute_point_cloud_distance(ref_pcd)
    )
    dist_ref_to_gen = np.asarray(
        ref_pcd.compute_point_cloud_distance(gen_pcd_final)
    )

    if dist_gen_to_ref.size == 0 or dist_ref_to_gen.size == 0:
        return {
            "chamfer_distance": None,
            "hausdorff_95p": None,
            "hausdorff_99p": None,
            "icp_fitness": icp_fitness,
            "bbox_passed": False,
        }

    # Chamfer distance: average of mean bidirectional distances
    chamfer = float(
        (np.mean(dist_gen_to_ref) + np.mean(dist_ref_to_gen)) / 2.0
    )

    # Hausdorff distances: percentiles of all bidirectional distances
    all_distances = np.concatenate((dist_gen_to_ref, dist_ref_to_gen))
    hausdorff_95p = float(np.percentile(all_distances, 95))
    hausdorff_99p = float(np.percentile(all_distances, 99))

    # --- Bounding box comparison after alignment ---
    gen_tm = trimesh.load(str(gen_path), force="mesh")
    ref_tm = trimesh.load(str(ref_path), force="mesh")
    gen_tm.apply_transform(final_transform)

    gen_dims = sorted(gen_tm.bounding_box.extents)
    ref_dims = sorted(ref_tm.bounding_box.extents)

    bbox_tolerance = config.get("bbox_tolerance_mm", 1.0)
    bbox_diffs = np.abs(np.array(gen_dims) - np.array(ref_dims))
    bbox_passed = bool(all(d <= bbox_tolerance for d in bbox_diffs))

    return {
        "chamfer_distance": chamfer,
        "hausdorff_95p": hausdorff_95p,
        "hausdorff_99p": hausdorff_99p,
        "icp_fitness": icp_fitness,
        "bbox_passed": bbox_passed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Mesh geometry alignment and validation pipeline"
    )
    parser.add_argument("generated", help="Path to generated STL file")
    parser.add_argument("reference", help="Path to reference STL file")
    parser.add_argument("config", help="Path to config YAML file")
    args = parser.parse_args()

    config = load_config(args.config)
    gen_path = Path(args.generated)
    ref_path = Path(args.reference)

    # --- Binary checks ---

    # Watertight check (generated mesh only)
    is_watertight = check_watertight(gen_path)

    # Component counting (generated mesh only)
    num_components = count_components(gen_path)
    expected_components = config.get("expected_components", 1)
    component_passed = num_components == expected_components

    # Volume comparison (both meshes must be watertight)
    gen_vol, ref_vol, vol_ratio, vol_percent_diff = compute_volumes(
        gen_path, ref_path
    )
    vol_threshold = config.get("volume_threshold_percent", 2.0)
    if vol_percent_diff is not None:
        vol_passed = vol_percent_diff <= vol_threshold
    else:
        vol_passed = False

    # --- Alignment and continuous metrics ---
    alignment_results = align_and_compute_metrics(gen_path, ref_path, config)

    chamfer = alignment_results["chamfer_distance"]
    h95 = alignment_results["hausdorff_95p"]
    h99 = alignment_results["hausdorff_99p"]
    icp_fitness = alignment_results["icp_fitness"]
    bbox_passed = alignment_results["bbox_passed"]

    # Apply thresholds
    chamfer_threshold = config.get("chamfer_threshold_mm", 1.0)
    hausdorff_threshold = config.get("hausdorff_threshold_mm", 1.0)

    chamfer_passed = chamfer is not None and chamfer <= chamfer_threshold
    hausdorff_passed = h95 is not None and h95 <= hausdorff_threshold

    # Overall result
    all_passed = all([
        is_watertight,
        component_passed,
        bbox_passed,
        vol_passed,
        chamfer_passed,
        hausdorff_passed,
    ])

    report = {
        "checks": {
            "watertight": is_watertight,
            "component_count": component_passed,
            "bounding_box": bbox_passed,
            "volume": vol_passed,
            "chamfer": chamfer_passed,
            "hausdorff": hausdorff_passed,
        },
        "metrics": {
            "chamfer_distance": chamfer,
            "hausdorff_95p": h95,
            "hausdorff_99p": h99,
            "icp_fitness": icp_fitness,
            "volume_ratio": vol_ratio,
            "generated_volume": gen_vol,
            "reference_volume": ref_vol,
        },
        "all_passed": all_passed,
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

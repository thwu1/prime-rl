#!/usr/bin/env python3
"""
Registration analysis pipeline with degeneracy detection and scene characterization.

Registers 5 scan pairs using GICP, analyses the Hessian eigenstructure to detect
geometric degeneracies, and characterizes each scene's observability profile.
"""

import json
import os

import numpy as np
import small_gicp


def determine_scene_type(pts):
    """Infer dominant scene geometry from PCA of the point cloud.

    Classifies based on the eigenvalue ratios of the point cloud's covariance
    matrix:
    - 'planar' if the smallest eigenvalue is negligible (flat surface)
    - 'cylindrical' if one eigenvalue dominates (elongated tube/tunnel)
    - 'multi_planar' if all eigenvalues are significant (box, room, etc.)
    """
    centered = pts - pts.mean(axis=0)
    cov = centered.T @ centered / len(centered)
    eigvals = np.sort(np.linalg.eigvalsh(cov))[::-1]  # descending

    r2 = eigvals[1] / max(eigvals[0], 1e-10)
    r3 = eigvals[2] / max(eigvals[0], 1e-10)

    if r3 < 0.001:
        return "planar"
    elif r2 < 0.3:
        return "cylindrical"
    else:
        return "multi_planar"


def process_scan(scan_dir, result_dir):
    target = np.loadtxt(os.path.join(scan_dir, "target.txt"))
    source = np.loadtxt(os.path.join(scan_dir, "source.txt"))

    # Characterize scene geometry from raw point distribution
    scene_type = determine_scene_type(target)

    # Preprocess with fine downsampling for better accuracy
    target_pc, target_tree = small_gicp.preprocess_points(
        target, downsampling_resolution=0.15, num_neighbors=20
    )
    source_pc, source_tree = small_gicp.preprocess_points(
        source, downsampling_resolution=0.15, num_neighbors=20
    )

    # Multi-pass registration for robust convergence:
    # Pass 1 — wide correspondence distance to find approximate alignment
    result = small_gicp.align(
        target_pc, source_pc, target_tree,
        max_correspondence_distance=5.0,
    )

    # Pass 2 — medium distance to refine
    result = small_gicp.align(
        target_pc, source_pc, target_tree,
        result.T_target_source,
        max_correspondence_distance=1.5,
    )

    # Pass 3 — tight distance for final accuracy and clean Hessian
    result = small_gicp.align(
        target_pc, source_pc, target_tree,
        result.T_target_source,
        max_correspondence_distance=0.5,
    )

    T = np.array(result.T_target_source)
    H = np.array(result.H)

    # Eigenvalue analysis of the 6x6 registration Hessian
    eigvals = np.sort(np.linalg.eigvalsh(H))
    eigvals = np.maximum(eigvals, 0.0)  # clip numerical noise

    max_eig = eigvals[-1]
    if max_eig > 1e-10:
        condition_number = float(eigvals[0] / max_eig)
        degenerate_dof_count = int(np.sum(eigvals < 0.01 * max_eig))
    else:
        condition_number = 0.0
        degenerate_dof_count = 6

    is_degenerate = degenerate_dof_count > 0

    # Write outputs
    os.makedirs(result_dir, exist_ok=True)

    with open(os.path.join(result_dir, "transform.json"), "w") as f:
        json.dump({"matrix": T.tolist()}, f)

    with open(os.path.join(result_dir, "hessian_eigenvalues.json"), "w") as f:
        json.dump({"eigenvalues": eigvals.tolist()}, f)

    with open(os.path.join(result_dir, "classification.json"), "w") as f:
        json.dump({
            "is_degenerate": is_degenerate,
            "condition_number": condition_number,
            "degenerate_dof_count": degenerate_dof_count,
        }, f)

    with open(os.path.join(result_dir, "diagnosis.json"), "w") as f:
        json.dump({
            "scene_type": scene_type,
            "registration_reliable": not is_degenerate,
            "num_well_constrained_dofs": 6 - degenerate_dof_count,
            "corrective_strategy": "multi_pass_refinement" if is_degenerate else None,
        }, f)

    print(f"  {scan_dir:30s}  scene={scene_type:15s}  "
          f"deg={str(is_degenerate):5s}  cond={condition_number:.4e}  "
          f"deg_dofs={degenerate_dof_count}")


def main():
    scans_dir = "/app/scans"
    results_dir = "/app/results"

    print("Registration analysis pipeline — processing scans")
    for i in range(1, 6):
        scan = f"scan_{i}"
        process_scan(
            os.path.join(scans_dir, scan),
            os.path.join(results_dir, scan),
        )
    print("Done.")


if __name__ == "__main__":
    main()

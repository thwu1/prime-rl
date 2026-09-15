"""
Rotation synchronization solver.

Recovers absolute rotations from noisy pairwise relative rotation measurements
in a pose graph. Implements two strategies (BFS init vs spectral init),
outlier rejection via geodesic residual analysis, and outputs comparison report.

"""

import json
import math
import os
import sys

import numpy as np
import torch

sys.path.insert(0, "/app")
from rotations_lib import (
    quaternion_to_matrix,
    axis_angle_to_matrix,
    euler_angles_to_matrix,
    so3_relative_angle,
    project_to_so3,
)


def load_pose_graph(path):
    with open(path) as f:
        return json.load(f)


def parse_rotation_to_matrix(rotation, fmt):
    """Convert a rotation in the given format to a 3x3 numpy matrix."""
    if fmt == "matrix":
        return np.array(rotation, dtype=np.float64)
    elif fmt == "quaternion":
        q = torch.tensor([rotation], dtype=torch.float64)
        R = quaternion_to_matrix(q)
        return R[0].numpy()
    elif fmt == "axis_angle":
        aa = torch.tensor([rotation], dtype=torch.float64)
        R = axis_angle_to_matrix(aa)
        return R[0].numpy()
    elif fmt == "euler_XYZ":
        ea = torch.tensor([rotation], dtype=torch.float64)
        R = euler_angles_to_matrix(ea, "XYZ")
        return R[0].numpy()
    else:
        raise ValueError(f"Unknown format: {fmt}")


def geodesic_angle_deg(R1, R2):
    """Geodesic angle in degrees between two 3x3 rotation matrices."""
    R12 = R1 @ R2.T
    trace = R12[0, 0] + R12[1, 1] + R12[2, 2]
    cos_angle = np.clip((trace - 1.0) / 2.0, -1.0, 1.0)
    return math.degrees(math.acos(cos_angle))


def project_np_to_so3(M):
    """Project a 3x3 matrix to SO(3) via SVD."""
    U, S, Vt = np.linalg.svd(M)
    det = np.linalg.det(U @ Vt)
    diag = np.array([1.0, 1.0, np.sign(det)])
    return U @ np.diag(diag) @ Vt


def build_adjacency(edges, num_nodes):
    """Build adjacency list from edges."""
    adj = {i: [] for i in range(num_nodes)}
    for idx, edge in enumerate(edges):
        i, j = edge["i"], edge["j"]
        adj[i].append((j, idx))
        adj[j].append((i, idx))
    return adj


# ============================================================
# Strategy A: BFS spanning tree initialization
# ============================================================

def bfs_init(num_nodes, edges, rel_rotations, anchors):
    """Initialize rotations via BFS from anchor node 0."""
    rotations = [None] * num_nodes

    # Set anchor rotations
    for key, R in anchors.items():
        rotations[int(key)] = np.array(R, dtype=np.float64)

    # BFS from node 0; mark all anchors as visited so they aren't overwritten
    adj = build_adjacency(edges, num_nodes)
    visited = set(int(k) for k in anchors.keys())
    queue = [0]

    while queue:
        node = queue.pop(0)
        for neighbor, edge_idx in adj[node]:
            if neighbor in visited:
                continue
            edge = edges[edge_idx]
            Rij = rel_rotations[edge_idx]
            i, j = edge["i"], edge["j"]

            if node == i:
                # Rij = R_j @ R_i^T => R_j = Rij @ R_i
                rotations[neighbor] = Rij @ rotations[node]
            else:
                # Rij = R_j @ R_i^T, node == j => R_i = Rij^T @ R_j
                rotations[neighbor] = Rij.T @ rotations[node]

            # Project to SO(3) to clean up numerical drift
            rotations[neighbor] = project_np_to_so3(rotations[neighbor])
            visited.add(neighbor)
            queue.append(neighbor)

    # If any nodes weren't reached, initialize to identity
    for k in range(num_nodes):
        if rotations[k] is None:
            rotations[k] = np.eye(3)

    return rotations


# ============================================================
# Strategy B: Spectral initialization
# ============================================================

def spectral_init(num_nodes, edges, rel_rotations, anchors):
    """Initialize rotations via spectral method on the connection Laplacian."""
    N = num_nodes
    # Build the 3N x 3N connection Laplacian
    # L_ii = degree(i) * I_3
    # L_ij = -R_ij (for edge (i,j))
    L = np.zeros((3 * N, 3 * N), dtype=np.float64)

    for idx, edge in enumerate(edges):
        i, j = edge["i"], edge["j"]
        Rij = rel_rotations[idx]

        # Add to off-diagonal blocks
        L[3*i:3*i+3, 3*j:3*j+3] -= Rij
        L[3*j:3*j+3, 3*i:3*i+3] -= Rij.T

        # Add to diagonal blocks (degree)
        L[3*i:3*i+3, 3*i:3*i+3] += np.eye(3)
        L[3*j:3*j+3, 3*j:3*j+3] += np.eye(3)

    # Add strong anchor constraints to fix gauge
    anchor_weight = 100.0
    for key, R_anchor in anchors.items():
        k = int(key)
        R_a = np.array(R_anchor, dtype=np.float64)
        # Add anchor_weight * (R_k - R_anchor)^2 to the objective
        L[3*k:3*k+3, 3*k:3*k+3] += anchor_weight * np.eye(3)

    # Find the 3 smallest eigenvectors
    eigenvalues, eigenvectors = np.linalg.eigh(L)

    # Take the first 3 eigenvectors (smallest eigenvalues)
    V = eigenvectors[:, :3]  # (3N, 3)

    # Extract and project rotations
    rotations = []
    for k in range(N):
        Mk = V[3*k:3*k+3, :]  # (3, 3)
        rotations.append(project_np_to_so3(Mk))

    # Align to anchor 0: find the global rotation G such that G @ R_0 = I
    R0 = rotations[0]
    anchor_R0 = np.array(anchors["0"], dtype=np.float64)
    G = anchor_R0 @ R0.T

    rotations = [project_np_to_so3(G @ R) for R in rotations]

    # Force anchors to exact values
    for key, R in anchors.items():
        rotations[int(key)] = np.array(R, dtype=np.float64)

    return rotations


# ============================================================
# Gauss-Seidel optimization
# ============================================================

def gauss_seidel_optimize(rotations, edges, rel_rotations, anchors,
                          edge_mask=None, max_iter=200, tol=1e-8):
    """Iteratively refine rotations using Gauss-Seidel updates.

    For each non-anchor node i, compute the weighted average of
    contributions from all neighboring edges, then project to SO(3).
    """
    N = len(rotations)
    rotations = [R.copy() for R in rotations]
    anchor_set = set(int(k) for k in anchors.keys())

    if edge_mask is None:
        edge_mask = [True] * len(edges)

    for iteration in range(max_iter):
        max_change = 0.0
        for node in range(N):
            if node in anchor_set:
                continue

            M = np.zeros((3, 3), dtype=np.float64)
            count = 0

            for idx, edge in enumerate(edges):
                if not edge_mask[idx]:
                    continue
                i, j = edge["i"], edge["j"]
                Rij = rel_rotations[idx]

                if i == node:
                    # Rij = R_j @ R_i^T => R_i = Rij^T @ R_j
                    M += Rij.T @ rotations[j]
                    count += 1
                elif j == node:
                    # Rij = R_j @ R_i^T => R_j = Rij @ R_i
                    M += Rij @ rotations[i]
                    count += 1

            if count > 0:
                R_new = project_np_to_so3(M)
                change = geodesic_angle_deg(rotations[node], R_new)
                max_change = max(max_change, change)
                rotations[node] = R_new

        if max_change < tol:
            break

    return rotations


# ============================================================
# Outlier detection
# ============================================================

def compute_edge_residuals(rotations, edges, rel_rotations):
    """Compute geodesic residual for each edge."""
    residuals = []
    for idx, edge in enumerate(edges):
        i, j = edge["i"], edge["j"]
        Rij = rel_rotations[idx]
        Rij_est = rotations[j] @ rotations[i].T
        residuals.append(geodesic_angle_deg(Rij, Rij_est))
    return residuals


def detect_outliers(residuals, edges):
    """Detect outliers using median + k*MAD threshold."""
    res = np.array(residuals)
    median = np.median(res)
    mad = np.median(np.abs(res - median))
    # Use a threshold of median + 3 * MAD * 1.4826 (scaled MAD)
    # or at least 15 degrees
    threshold = max(median + 3.0 * mad * 1.4826, 15.0)

    outlier_pairs = []
    outlier_mask = [True] * len(edges)
    for idx, (edge, r) in enumerate(zip(edges, residuals)):
        if r > threshold:
            outlier_pairs.append([edge["i"], edge["j"]])
            outlier_mask[idx] = False

    return outlier_pairs, outlier_mask, threshold


# ============================================================
# Main pipeline
# ============================================================

def run_strategy(name, init_fn, num_nodes, edges, rel_rotations, anchors):
    """Run a full strategy: init -> optimize -> detect outliers -> re-optimize."""
    rotations = init_fn(num_nodes, edges, rel_rotations, anchors)
    rotations = gauss_seidel_optimize(rotations, edges, rel_rotations, anchors)

    residuals = compute_edge_residuals(rotations, edges, rel_rotations)
    outlier_pairs, edge_mask, threshold = detect_outliers(residuals, edges)

    # Re-optimize without outliers
    rotations = gauss_seidel_optimize(rotations, edges, rel_rotations, anchors, edge_mask)

    # Compute final residuals (inliers only)
    final_residuals = compute_edge_residuals(rotations, edges, rel_rotations)
    inlier_residuals = [r for r, m in zip(final_residuals, edge_mask) if m]
    mean_residual = np.mean(inlier_residuals) if inlier_residuals else 0.0

    return {
        "name": name,
        "rotations": rotations,
        "outlier_pairs": outlier_pairs,
        "threshold": threshold,
        "mean_residual_deg": float(mean_residual),
    }


def main():
    pg = load_pose_graph("/app/pose_graph.json")
    num_nodes = pg["num_nodes"]
    edges = pg["edges"]
    anchors = pg["anchors"]

    # Parse all relative rotations to matrices
    rel_rotations = []
    for edge in edges:
        R = parse_rotation_to_matrix(edge["rotation"], edge["format"])
        rel_rotations.append(R)

    # Run both strategies
    result_a = run_strategy(
        "BFS spanning tree",
        bfs_init,
        num_nodes, edges, rel_rotations, anchors,
    )

    result_b = run_strategy(
        "Spectral initialization",
        spectral_init,
        num_nodes, edges, rel_rotations, anchors,
    )

    # Choose better strategy
    if result_a["mean_residual_deg"] <= result_b["mean_residual_deg"]:
        chosen = result_a
    else:
        chosen = result_b

    # Write rotations
    os.makedirs("/app/output", exist_ok=True)

    rot_out = {}
    for i, R in enumerate(chosen["rotations"]):
        rot_out[str(i)] = [[float(R[r][c]) for c in range(3)] for r in range(3)]
    with open("/app/output/rotations.json", "w") as f:
        json.dump(rot_out, f, indent=2)

    # Write outliers
    with open("/app/output/outliers.json", "w") as f:
        json.dump(chosen["outlier_pairs"], f, indent=2)

    # Write report
    report = {
        "strategy_a_name": result_a["name"],
        "strategy_b_name": result_b["name"],
        "strategy_a_mean_residual_deg": result_a["mean_residual_deg"],
        "strategy_b_mean_residual_deg": result_b["mean_residual_deg"],
        "chosen_strategy": chosen["name"],
        "outlier_threshold_deg": chosen["threshold"],
    }
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Strategy A ({result_a['name']}): mean residual = {result_a['mean_residual_deg']:.4f}°")
    print(f"Strategy B ({result_b['name']}): mean residual = {result_b['mean_residual_deg']:.4f}°")
    print(f"Chosen: {chosen['name']}")
    print(f"Outliers detected: {chosen['outlier_pairs']}")
    print(f"Outlier threshold: {chosen['threshold']:.2f}°")
    print("Done. Outputs written to /app/output/")


if __name__ == "__main__":
    main()

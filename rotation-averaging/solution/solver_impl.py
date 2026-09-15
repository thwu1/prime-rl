#!/usr/bin/env python3
"""Robust rotation averaging solver for Structure-from-Motion.

Implements:
1. Maximum spanning tree initialization of global rotations
2. Chordal IRLS refinement via block coordinate descent on SO(3)
3. Outlier detection via geodesic residual thresholding
"""

import json
import os

import networkx as nx
import numpy as np
from scipy.spatial.transform import Rotation


# -----------------------------------------------------------------------
# SO(3) utilities
# -----------------------------------------------------------------------

def geodesic_distance(R1, R2):
    """Geodesic (angular) distance between two rotations, in radians."""
    R_rel = R1.T @ R2
    cos_a = np.clip((np.trace(R_rel) - 1) / 2, -1.0, 1.0)
    return float(np.arccos(cos_a))


def svd_project_so3(M):
    """Project a 3x3 matrix onto SO(3) via SVD."""
    U, _, Vt = np.linalg.svd(M)
    d = np.linalg.det(U @ Vt)
    return U @ np.diag([1.0, 1.0, d]) @ Vt


# -----------------------------------------------------------------------
# MST initialization
# -----------------------------------------------------------------------

def mst_initialize(num_cameras, edges):
    """Initialize global rotations by chaining relatives along the MST.

    Builds a graph with edge weights = confidence, extracts the maximum
    spanning tree, and propagates rotations from node 0 via DFS.
    """
    G = nx.Graph()
    G.add_nodes_from(range(num_cameras))

    # For duplicate (i,j) pairs keep the highest-weight edge
    best_edge = {}
    for idx, e in enumerate(edges):
        pair = (e["i"], e["j"])
        if pair not in best_edge or e["weight"] > edges[best_edge[pair]]["weight"]:
            best_edge[pair] = idx
    for pair, idx in best_edge.items():
        i, j = pair
        w = edges[idx]["weight"]
        if G.has_edge(i, j):
            if w > G[i][j]["weight"]:
                G[i][j]["weight"] = w
                G[i][j]["edge_idx"] = idx
        else:
            G.add_edge(i, j, weight=w, edge_idx=idx)

    mst = nx.maximum_spanning_tree(G)

    rotations = {i: np.eye(3, dtype=np.float64) for i in range(num_cameras)}
    visited = {0}
    stack = [(0, list(mst.neighbors(0)))]

    while stack:
        node, nbrs = stack[-1]
        if not nbrs:
            stack.pop()
            continue
        nbr = nbrs.pop()
        if nbr in visited:
            continue
        visited.add(nbr)

        edge_idx = mst[node][nbr]["edge_idx"]
        e = edges[edge_idx]
        R_ij = np.array(e["R_ij"], dtype=np.float64)

        if e["i"] == node and e["j"] == nbr:
            # Convention: R_j = R_ij @ R_i
            rotations[nbr] = R_ij @ rotations[node]
        else:
            # Edge stored as (nbr, node): R_ij = R_node @ R_nbr^T
            # => R_nbr = R_ij^T @ R_node
            rotations[nbr] = R_ij.T @ rotations[node]

        rotations[nbr] = svd_project_so3(rotations[nbr])
        stack.append((nbr, list(mst.neighbors(nbr))))

    return rotations


# -----------------------------------------------------------------------
# Chordal IRLS via block coordinate descent
# -----------------------------------------------------------------------

def chordal_irls_averaging(num_cameras, edges, rotations,
                            max_iter=200, tol=1e-8, huber_delta=0.1):
    """Refine rotations via IRLS with chordal cost and block coordinate descent.

    Minimises sum_k w_k ||R_ij^(k) - R_j R_i^T||_F^2 with Huber IRLS
    reweighting based on geodesic residuals.  Each camera update is the
    SVD projection of a weighted sum of target matrices — an exact
    minimiser of the chordal sub-problem given all other cameras fixed.
    Camera 0 is held fixed for gauge.
    """
    edge_base_weights = np.array([e["weight"] for e in edges])

    # Pre-parse rotation matrices for speed
    edge_R = [np.array(e["R_ij"], dtype=np.float64) for e in edges]

    # Build adjacency lists: for each camera, which edges involve it
    adj = [[] for _ in range(num_cameras)]
    for k, e in enumerate(edges):
        adj[e["i"]].append(k)
        adj[e["j"]].append(k)

    for it in range(max_iter):
        # --- Compute geodesic residuals for IRLS weights ---
        residuals = np.zeros(len(edges))
        for k, e in enumerate(edges):
            R_est = rotations[e["j"]] @ rotations[e["i"]].T
            residuals[k] = geodesic_distance(edge_R[k], R_est)

        # Huber weights: down-weight edges with large residuals
        weights = edge_base_weights.copy()
        large = residuals > huber_delta
        weights[large] *= huber_delta / np.maximum(residuals[large], 1e-12)

        # --- Block coordinate descent sweep ---
        old_rotations = [rotations[i].copy() for i in range(num_cameras)]

        for j in range(1, num_cameras):  # camera 0 stays fixed (gauge)
            M = np.zeros((3, 3))
            for k in adj[j]:
                e = edges[k]
                w = weights[k]
                if e["j"] == j:
                    # Edge (e["i"] -> j): R_j = R_ij R_i
                    # Chordal target for R_j: R_ij @ R_i
                    M += w * edge_R[k] @ rotations[e["i"]]
                elif e["i"] == j:
                    # Edge (j -> e["j"]): R_{e["j"]} = R_ij R_j
                    # => R_j = R_ij^T R_{e["j"]}
                    # Chordal target for R_j: R_ij^T @ R_{e["j"]}
                    M += w * edge_R[k].T @ rotations[e["j"]]

            if np.linalg.norm(M) < 1e-12:
                continue
            rotations[j] = svd_project_so3(M)

        # --- Check convergence ---
        max_change = max(
            geodesic_distance(rotations[i], old_rotations[i])
            for i in range(num_cameras)
        )
        if max_change < tol:
            break

    return rotations, it + 1


# -----------------------------------------------------------------------
# Outlier detection
# -----------------------------------------------------------------------

def detect_outliers(edges, rotations, threshold_deg=8.0):
    """Flag edges whose geodesic residual exceeds the threshold."""
    outliers = []
    for e in edges:
        i, j = e["i"], e["j"]
        R_ij = np.array(e["R_ij"], dtype=np.float64)
        R_est = rotations[j] @ rotations[i].T
        err_deg = np.degrees(geodesic_distance(R_ij, R_est))
        if err_deg > threshold_deg:
            outliers.append([int(i), int(j)])
    return outliers


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main():
    with open("/app/pose_graph.json") as f:
        pg = json.load(f)

    num_cameras = pg["num_cameras"]
    edges = pg["edges"]

    # Step 1: MST initialisation
    rotations = mst_initialize(num_cameras, edges)

    # Step 2: Chordal IRLS refinement
    rotations, n_iter = chordal_irls_averaging(num_cameras, edges, rotations)

    # Step 3: Outlier detection
    outliers = detect_outliers(edges, rotations)

    # Write results
    os.makedirs("/app/output", exist_ok=True)
    result = {
        "rotations": {
            str(i): rotations[i].tolist() for i in range(num_cameras)
        },
        "outlier_edges": outliers,
    }
    with open("/app/output/results.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Converged in {n_iter} iterations, "
          f"detected {len(outliers)} outlier edges")


if __name__ == "__main__":
    main()

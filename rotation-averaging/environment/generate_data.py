#!/usr/bin/env python3
"""Generate synthetic pose graph for rotation averaging benchmark."""
import json
import os

import numpy as np
from scipy.spatial.transform import Rotation


def generate_pose_graph(seed=42):
    """Generate a pose graph with inlier and outlier relative rotations.

    Returns:
        (pose_graph, ground_truth) where pose_graph is the solver input
        and ground_truth contains the true rotations and outlier labels.
    """
    rng = np.random.default_rng(seed)
    num_cameras = 25

    # Ground truth rotations (random SO(3) elements)
    gt_rotations = []
    for _ in range(num_cameras):
        gt_rotations.append(Rotation.random(random_state=rng).as_matrix())

    def geodesic_dist(R1, R2):
        R_rel = R1.T @ R2
        cos_a = np.clip((np.trace(R_rel) - 1) / 2, -1.0, 1.0)
        return float(np.arccos(cos_a))

    # Build k-NN graph in rotation space to ensure connectivity
    k = 6
    edge_set = set()
    for i in range(num_cameras):
        dists = []
        for j in range(num_cameras):
            if i == j:
                continue
            dists.append((geodesic_dist(gt_rotations[i], gt_rotations[j]), j))
        dists.sort()
        for _, j in dists[:k]:
            edge_set.add((min(i, j), max(i, j)))

    # Add random edges for additional connectivity
    for _ in range(20):
        i = int(rng.integers(0, num_cameras))
        j = int(rng.integers(0, num_cameras))
        if i != j:
            edge_set.add((min(i, j), max(i, j)))

    # Create inlier edges with small Gaussian noise
    noise_std = 0.008  # radians (~0.46 degrees)
    edges = []
    edge_is_outlier = []

    for i, j in sorted(edge_set):
        R_ij_gt = gt_rotations[j] @ gt_rotations[i].T
        R_noise = Rotation.from_rotvec(rng.normal(0, noise_std, size=3)).as_matrix()
        R_ij = R_noise @ R_ij_gt

        dist = geodesic_dist(gt_rotations[i], gt_rotations[j])
        weight = float(np.clip(1.0 - 0.3 * dist, 0.3, 1.0))

        edges.append({
            "i": int(i),
            "j": int(j),
            "R_ij": R_ij.tolist(),
            "weight": round(weight, 4),
        })
        edge_is_outlier.append(False)

    # Add outlier edges with random rotations and lower weights
    num_outliers = 15
    for _ in range(num_outliers):
        i = int(rng.integers(0, num_cameras))
        j = int(rng.integers(0, num_cameras))
        while i == j:
            j = int(rng.integers(0, num_cameras))
        i, j = min(i, j), max(i, j)

        R_random = Rotation.random(random_state=rng).as_matrix()
        weight = float(round(rng.uniform(0.15, 0.45), 4))

        edges.append({
            "i": i,
            "j": j,
            "R_ij": R_random.tolist(),
            "weight": weight,
        })
        edge_is_outlier.append(True)

    pose_graph = {"num_cameras": num_cameras, "edges": edges}
    ground_truth = {
        "rotations": [R.tolist() for R in gt_rotations],
        "edge_is_outlier": edge_is_outlier,
    }
    return pose_graph, ground_truth


if __name__ == "__main__":
    pg, _ = generate_pose_graph(seed=42)
    os.makedirs("/app", exist_ok=True)
    with open("/app/pose_graph.json", "w") as f:
        json.dump(pg, f, indent=2)
    print(f"Generated: {pg['num_cameras']} cameras, {len(pg['edges'])} edges")

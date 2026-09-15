"""Solution for TDA point cloud classification task.

Computes persistent homology, extracts topological features,
classifies point clouds by shape type, and computes stability scores.
"""

import numpy as np
import json
import gudhi


def compute_persistence_diagrams(points, max_edge_length=4.0, max_dim=3):
    """Compute persistence diagrams for a point cloud.

    Returns a dict mapping homology dimension to an array of (birth, death)
    pairs for finite-lifetime features.
    """
    rips = gudhi.RipsComplex(points=points.tolist(), max_edge_length=max_edge_length)
    st = rips.create_simplex_tree(max_dimension=1)
    st.collapse_edges()
    st.expansion(max_dim)
    st.compute_persistence()

    diagrams = {}
    for dim in [0, 1, 2]:
        intervals = st.persistence_intervals_in_dimension(dim)
        if len(intervals) == 0:
            diagrams[dim] = np.empty((0, 2))
            continue
        finite_mask = np.isfinite(intervals[:, 1])
        if np.any(finite_mask):
            diagrams[dim] = intervals[finite_mask]
        else:
            diagrams[dim] = np.empty((0, 2))
    return diagrams


def persistence_entropy_base2(diagram):
    """Compute Shannon entropy (base 2) of the persistence lifetime distribution."""
    if len(diagram) == 0:
        return 0.0
    lifetimes = diagram[:, 1] - diagram[:, 0]
    total = np.sum(lifetimes)
    if total <= 0:
        return 0.0
    probs = lifetimes / total
    probs = probs[probs > 0]
    return float(-np.sum(probs * np.log2(probs)))


def count_significant_features(diagram, threshold_frac=0.1):
    """Count features with persistence > threshold_frac * max_persistence."""
    if len(diagram) == 0:
        return 0
    lifetimes = diagram[:, 1] - diagram[:, 0]
    max_pers = np.max(lifetimes)
    if max_pers <= 0:
        return 0
    threshold = threshold_frac * max_pers
    return int(np.sum(lifetimes > threshold))


def max_persistence(diagram):
    """Return maximum finite persistence (bottleneck amplitude)."""
    if len(diagram) == 0:
        return 0.0
    lifetimes = diagram[:, 1] - diagram[:, 0]
    return float(np.max(lifetimes))


def bottleneck_dist(diag1, diag2):
    """Compute bottleneck distance between two persistence diagrams."""
    if len(diag1) == 0 and len(diag2) == 0:
        return 0.0
    if len(diag1) == 0:
        lifetimes = diag2[:, 1] - diag2[:, 0]
        return float(np.max(lifetimes) / 2.0)
    if len(diag2) == 0:
        lifetimes = diag1[:, 1] - diag1[:, 0]
        return float(np.max(lifetimes) / 2.0)
    return float(gudhi.bottleneck_distance(diag1, diag2))


def classify_shape(amplitudes):
    """Classify a point cloud as circle (0), sphere (1), or torus (2).

    Uses amplitude ratios across dimensions:
    - Sphere: H2 amplitude exceeds H1
    - Torus: H0 amplitude exceeds H1
    - Circle: H1 amplitude dominates
    """
    amp_h0 = amplitudes[0]
    amp_h1 = amplitudes[1]
    amp_h2 = amplitudes[2]

    if amp_h2 > amp_h1:
        return 1  # sphere
    if amp_h0 > amp_h1:
        return 2  # torus
    return 0  # circle


def main():
    point_clouds = np.load('/app/data/point_clouds.npy')
    n_clouds = point_clouds.shape[0]

    print(f"Loaded {n_clouds} point clouds of shape {point_clouds.shape}")

    # Compute persistence diagrams for all clouds
    all_diagrams = []
    for i in range(n_clouds):
        print(f"Computing persistence for cloud {i}...")
        diag = compute_persistence_diagrams(point_clouds[i], max_edge_length=4.0)
        all_diagrams.append(diag)

    # Extract features
    persistence_entropies = []
    significant_features = []
    bottleneck_amplitudes = []

    for i in range(n_clouds):
        pe_row = []
        sf_row = []
        ba_row = []
        for dim in [0, 1, 2]:
            d = all_diagrams[i][dim]
            pe_row.append(persistence_entropy_base2(d))
            sf_row.append(count_significant_features(d))
            ba_row.append(max_persistence(d))
        persistence_entropies.append(pe_row)
        significant_features.append(sf_row)
        bottleneck_amplitudes.append(ba_row)

    print("Feature extraction complete.")
    for i in range(n_clouds):
        print(f"  Cloud {i}: sig_features={significant_features[i]}, "
              f"amplitudes=[{bottleneck_amplitudes[i][0]:.3f}, "
              f"{bottleneck_amplitudes[i][1]:.3f}, "
              f"{bottleneck_amplitudes[i][2]:.3f}]")

    # Classify shapes
    shape_labels = []
    for i in range(n_clouds):
        label = classify_shape(bottleneck_amplitudes[i])
        shape_labels.append(label)

    print(f"Shape labels: {shape_labels}")

    # Compute H1 pairwise bottleneck distance matrix
    print("Computing pairwise H1 bottleneck distances...")
    distance_matrix_h1 = np.zeros((n_clouds, n_clouds))
    for i in range(n_clouds):
        for j in range(i + 1, n_clouds):
            d = bottleneck_dist(all_diagrams[i][1], all_diagrams[j][1])
            distance_matrix_h1[i, j] = d
            distance_matrix_h1[j, i] = d

    # Find most similar and most dissimilar pairs
    min_dist = float('inf')
    max_dist = -float('inf')
    most_similar = [0, 1]
    most_dissimilar = [0, 1]

    for i in range(n_clouds):
        for j in range(i + 1, n_clouds):
            d = distance_matrix_h1[i, j]
            if d > 0 and d < min_dist:
                min_dist = d
                most_similar = [i, j]
            if d > max_dist:
                max_dist = d
                most_dissimilar = [i, j]

    if min_dist == float('inf'):
        most_similar = [0, 1]

    print(f"Most similar pair: {most_similar} (dist={min_dist:.4f})")
    print(f"Most dissimilar pair: {most_dissimilar} (dist={max_dist:.4f})")

    # Compute stability scores
    print("Computing stability scores...")
    stability_scores = []
    for i in range(n_clouds):
        full_h1 = all_diagrams[i][1]
        dists = []

        for seed in range(5):
            rng = np.random.RandomState(seed)
            n_points = point_clouds.shape[1]
            indices = rng.choice(n_points, size=int(0.8 * n_points), replace=False)
            subsample = point_clouds[i][indices]

            sub_diag = compute_persistence_diagrams(subsample, max_edge_length=4.0)
            sub_h1 = sub_diag[1]

            d = bottleneck_dist(full_h1, sub_h1)
            dists.append(d)

        avg_dist = np.mean(dists)
        score = 1.0 / (1.0 + avg_dist)
        stability_scores.append(float(score))
        print(f"  Cloud {i}: avg_bottleneck_dist={avg_dist:.4f}, "
              f"stability={score:.4f}")

    # Write results
    results = {
        "persistence_entropies": [[float(v) for v in row]
                                  for row in persistence_entropies],
        "significant_features": [[int(v) for v in row]
                                 for row in significant_features],
        "bottleneck_amplitudes": [[float(v) for v in row]
                                  for row in bottleneck_amplitudes],
        "shape_labels": [int(l) for l in shape_labels],
        "distance_matrix_h1": [[float(v) for v in row]
                               for row in distance_matrix_h1.tolist()],
        "most_similar_pair": most_similar,
        "most_dissimilar_pair": most_dissimilar,
        "stability_scores": [float(s) for s in stability_scores],
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()

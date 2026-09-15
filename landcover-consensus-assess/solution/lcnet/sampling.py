"""CDF-based stratified geospatial tile sampling."""

import numpy as np


def stratified_sample(features, n, seed=None):
    features = np.asarray(features, dtype=float)
    n_tiles, n_features = features.shape

    if n >= n_tiles:
        return np.arange(n_tiles)

    rng = np.random.RandomState(seed)

    cdf = np.zeros_like(features)
    for j in range(n_features):
        col = features[:, j]
        sorted_indices = np.argsort(col, kind='mergesort')
        ranks = np.empty(n_tiles, dtype=float)
        ranks[sorted_indices] = np.arange(1, n_tiles + 1, dtype=float)
        unique_vals = np.unique(col)
        for v in unique_vals:
            mask = col == v
            if mask.sum() > 1:
                ranks[mask] = ranks[mask].mean()
        cdf[:, j] = ranks / n_tiles

    centroid = cdf.mean(axis=0)
    dists = np.linalg.norm(cdf - centroid, axis=1)
    dists = dists + rng.uniform(0, 1e-12, size=n_tiles)
    first = int(np.argmin(dists))
    selected = [first]

    min_dists = np.full(n_tiles, np.inf)
    for _ in range(n - 1):
        last = selected[-1]
        d = np.linalg.norm(cdf - cdf[last], axis=1)
        min_dists = np.minimum(min_dists, d)

        candidates = min_dists.copy()
        for s in selected:
            candidates[s] = -np.inf
        candidates = candidates + rng.uniform(0, 1e-12, size=n_tiles)
        for s in selected:
            candidates[s] = -np.inf

        selected.append(int(np.argmax(candidates)))

    return np.array(selected)

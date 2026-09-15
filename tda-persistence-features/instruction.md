`/app/data/point_clouds.npy` contains 12 point clouds as a NumPy array of shape `(12, 100, 3)`. The clouds were sampled from three geometric surface types — circle (genus-0 closed curve), sphere, and torus — four clouds per type, each with a different level of Gaussian noise. The ordering of types within the array is unknown; you must determine which clouds belong to which type by analyzing the data.

See `/app/data/metadata.json` for basic dataset properties.

Produce `/app/results.json` with the following fields (all arrays use 0-based indexing matching the cloud ordering in the `.npy` file):

- `"persistence_entropies"` — 12×3 float array. For each cloud and homology dimension (0, 1, 2): Shannon entropy (base 2) of the normalized persistence lifetime distribution over finite-lifetime features. Lifetimes = `death − birth`; probabilities = `lifetime_i / sum(lifetimes)`. Use `0.0` if no finite-lifetime features exist.

- `"significant_features"` — 12×3 integer array. For each cloud and dimension: count of features whose persistence exceeds 10% of the maximum finite persistence in that dimension for that cloud. Zero if no finite features.

- `"bottleneck_amplitudes"` — 12×3 float array. Maximum finite persistence per homology dimension per cloud. `0.0` if none.

- `"shape_labels"` — 12-element integer array. Classification of each cloud: `0` = circle, `1` = sphere, `2` = torus.

- `"distance_matrix_h1"` — 12×12 float array. Pairwise bottleneck distances on H1 persistence diagrams (finite-lifetime features only).

- `"most_similar_pair"` — `[i, j]` with `i < j`: index pair with the smallest positive H1 bottleneck distance.

- `"most_dissimilar_pair"` — `[i, j]` with `i < j`: index pair with the largest H1 bottleneck distance.

- `"stability_scores"` — 12-element float array. For each cloud: draw 5 subsamples of 80 points using `numpy.random.RandomState(seed)` for seeds 0–4 (indices selected without replacement), compute H1 persistence for each subsample, then the bottleneck distance to the full cloud's H1 diagram. Report `1.0 / (1.0 + mean_distance)`.

## Acceptance criteria

- Classification accuracy ≥ 10/12 against ground-truth labels.
- Topological features must reflect actual geometry:
  - Each circle cloud: ≥ 1 significant H1 feature; H2 amplitude strictly less than H1 amplitude.
  - At least 2 of the 4 sphere clouds: ≥ 1 significant H2 feature.
  - At least 2 of the 4 torus clouds: ≥ 2 significant H1 features.
  - All 12 clouds: ≥ 1 significant H0 feature.
- H1 distance matrix: symmetric, non-negative, zero diagonal, all values finite.
- Average intra-class H1 distance < average inter-class H1 distance.
- Most-similar pair distance ≤ most-dissimilar pair distance.
- Persistence entropies: non-negative and finite.
- Bottleneck amplitudes: non-negative.
- Significant feature counts: non-negative integers.
- Stability scores: in (0, 1] and finite.
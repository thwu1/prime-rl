A calibration dataset at `/app/data/correspondences.json` contains 2D point correspondences between 5 camera views of a planar calibration target. The correspondences include ~15% gross outliers. The file also provides the shared camera intrinsic matrix and image dimensions.

Implement a complete multi-view homography estimation pipeline that:

1. Robustly estimates pairwise homographies from the noisy correspondences using RANSAC with the normalized Direct Linear Transform (DLT), classifying each correspondence as inlier or outlier.

2. Recovers globally consistent view-to-reference homographies `H_0, ..., H_4` (with `H_0 = I`) by chaining pairwise estimates through a minimum spanning tree weighted by inlier reprojection error, then performs nonlinear refinement (Levenberg-Marquardt) minimizing total squared reprojection error across all inlier correspondences simultaneously.

3. Decomposes each pairwise homography `H_ij` (between views sharing the known intrinsic matrix `K`) into the underlying rotation matrix `R`, normalized translation direction `t/||t||`, and plane normal vector `n`, disambiguating the four SVD solutions using positive-depth constraints from the inlier points.

Write outputs to `/app/output/`:

- `homographies.json` — object with keys `"H_0"` through `"H_4"`, each a 3x3 matrix (list of 3 lists of 3 floats), representing view-to-reference-frame homographies. `H_0` must be the 3x3 identity. Each `H_i` maps a point in the reference frame to the corresponding point in view `i`. Normalize each so `H[2][2] = 1.0`.

- `inliers.json` — object with keys like `"0-1"`, `"0-2"`, ..., `"3-4"` for all 10 view pairs. Each value is a list of booleans (same length as the correspondence list for that pair) indicating inlier (`true`) or outlier (`false`).

- `metrics.json` — object containing:
  - `"per_pair_rms"`: object mapping pair keys to RMS reprojection error (pixels) over inliers for that pair using the globally refined homographies.
  - `"global_rms"`: overall RMS across all inlier correspondences.
  - `"consistency_error"`: maximum Frobenius norm of `H_i @ inv(H_j) - H_ij_direct` across all pairs where `H_ij_direct` is the direct pairwise estimate, after normalizing both so `[2][2] = 1`.

- `decompositions.json` — object with keys `"0-1"` through `"3-4"`. Each value is an object with:
  - `"R"`: 3x3 rotation matrix (list of lists)
  - `"t"`: 3-element normalized translation direction
  - `"n"`: 3-element plane normal vector (unit length, oriented so the plane is in front of both cameras)
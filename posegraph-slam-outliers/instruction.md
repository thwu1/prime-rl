A 2D pose graph SLAM dataset is provided at `/app/pose_graph.json`. It contains 100 robot poses connected by noisy odometry edges (sequential) and loop closure edges (non-sequential). Five of the loop closure edges are **outliers** -- false positive detections with fundamentally incorrect measurements that would corrupt a naive least-squares solution.

Implement a pose graph optimizer that produces `/app/optimized_poses.json` with this exact JSON structure:

```json
{
  "poses": [[x0, y0, theta0], [x1, y1, theta1], ...],
  "rejected_loop_closures": [3, 7, 12]
}
```

The `poses` array must contain exactly 100 entries, each a 3-element list `[x, y, theta]` of numeric values. The `rejected_loop_closures` array must contain integer indices into the `loop_closure_edges` array identifying detected outliers.

## Dataset format

Each edge has fields `i`, `j` (pose indices), `dx`, `dy`, `dtheta` (relative measurement in pose `i`'s local frame), and `information` -- the upper triangle `[i11, i12, i13, i22, i23, i33]` of the symmetric 3x3 information (inverse covariance) matrix.

## Optimization requirements

- Minimize the total weighted constraint residual across all edges using iterative nonlinear optimization on the SE(2) manifold.
- Properly handle angle normalization to [-pi, pi) throughout.
- Fix pose 0 as the gauge reference -- it must not move more than 0.01m from its initial position.
- The optimized poses must differ meaningfully from the raw initial estimates (i.e., optimization must actually run and modify the poses).

## Outlier detection requirements

- Detect and reject outlier loop closures. There are exactly 5 outlier edges among the loop closures.
- At least 3 of the 5 outliers must be correctly identified in `rejected_loop_closures`.
- At most 2 correct (non-outlier) loop closures may be falsely rejected.

## Accuracy requirements

- Per-pose position error (Euclidean) must be below 0.5 meters for every pose.
- Mean position error across all poses must be below 0.2 meters.
- Per-pose orientation error must be below 0.1 radians for every pose.
- Mean orientation error across all poses must be below 0.05 radians.

## Residual consistency requirements

- For every odometry edge, the weighted chi-squared residual (e^T * Omega * e, where e is the measurement residual and Omega is the information matrix) must be below 50.
- For every accepted (non-rejected) loop closure edge, the weighted chi-squared residual must also be below 50.
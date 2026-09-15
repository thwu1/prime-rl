A 3D LiDAR SLAM pose graph is provided at `/app/data/trajectory.g2o` in standard g2o format. It encodes 16 poses forming a rectangular loop trajectory connected by 15 sequential odometry edges and 4 loop closure edges. Some loop closure edges are outliers containing fabricated relative transformations.

Create `/app/optimize.py` that reads the g2o pose graph, optimizes all poses to minimize measurement residuals while detecting and rejecting outlier edges, and writes the outputs described below. External graph optimization or manifold optimization libraries (gtsam, g2o library, ceres, scipy.optimize) are not permitted — only numpy and scipy linear algebra primitives.

## g2o Input Format

`/app/data/trajectory.g2o` uses SE(3) quaternion conventions:

- `VERTEX_SE3:QUAT id x y z qx qy qz qw` — initial pose estimate as position + unit quaternion (Hamilton convention, scalar-last)
- `EDGE_SE3:QUAT from to dx dy dz dqx dqy dqz dqw <21 values>` — relative pose constraint followed by the upper triangle (row-major) of the 6×6 information matrix in `[tx ty tz rx ry rz]` ordering
- `FIX id` — anchor pose index (must remain unchanged during optimization)

## Required Outputs

1. **`/app/output/poses.json`** — JSON list of `{"id": int, "pose": <4×4 matrix>}`. Each pose must be a valid SE(3) matrix: det(R)≈1 and R·Rᵀ≈I within 0.05 tolerance.

2. **`/app/output/outliers.json`** — JSON list of `{"edge_index": int, "from": int, "to": int}` identifying outlier edges. Must detect all true outliers with at most 1 false positive. `edge_index` is the 0-based appearance order of `EDGE_SE3:QUAT` lines in the g2o file.

3. **`/app/output/optimized.g2o`** — Optimized pose graph written back in g2o format with updated `VERTEX_SE3:QUAT` lines containing optimized positions and orientations, plus the same edges and `FIX` line as the input. Must contain exactly 16 vertices and 19 edges. Output quaternions must be unit-normalized (‖q‖ within 0.01 of 1.0).

4. **`/app/output/trajectory.png`** — Bird's-eye-view XY trajectory comparison plot generated with `gnuplot`, showing initial and optimized trajectories as two distinct labeled series. Must be a valid PNG file of at least 1 KB.

## Accuracy Thresholds

- Maximum translation error per pose: < 0.5 m
- Average translation error across all poses: < 0.2 m
- Maximum rotation error per pose: < 5°
- Average rotation error: < 2°
- The anchor (fixed) pose must remain identical to its initial value (tolerance 1e-4)
- Euclidean distance between poses 15 and 0 must be within 0.5 m of the ground truth distance

The optimizer must generalize: it will be re-run on a second independently-generated pose graph of identical structure but different random seed, where it must achieve max translation error < 0.7 m, average < 0.3 m, and detect all outliers.
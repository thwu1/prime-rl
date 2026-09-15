# SLAM Trajectory Evaluation — Mathematical Specification

## 1. Trajectory Formats

### KITTI
- One line per pose: 12 space-separated floats
- Row-major 3x4 transformation matrix `[R|t]`:
  `r00 r01 r02 tx r10 r11 r12 ty r20 r21 r22 tz`
- Poses indexed by line number (zero-based, no timestamps)

### TUM
- Lines starting with `#` are comments (skip them)
- Data lines: `timestamp tx ty tz qx qy qz qw`
- Quaternion convention: Hamilton scalar-last `(qx, qy, qz, qw)`

### EuRoC Ground Truth
- CSV format; first line is a header starting with `#`
- Columns: `timestamp_ns, px, py, pz, qw, qx, qy, qz, vx, vy, vz, ...`
- **Timestamps are in nanoseconds** — must be converted to seconds (multiply by 1e-9) for association with estimated trajectories
- **Quaternion order is scalar-FIRST**: `(qw, qx, qy, qz)` — differs from TUM's scalar-last convention
- Estimated trajectories for EuRoC evaluation use TUM format (seconds, scalar-last quaternions)

### Quaternion to Rotation Matrix

Given a unit quaternion `(qx, qy, qz, qw)` in scalar-last form, the rotation matrix is:

```
R = [[1 - 2(qy² + qz²),  2(qx·qy - qz·qw),  2(qx·qz + qy·qw)],
     [2(qx·qy + qz·qw),  1 - 2(qx² + qz²),  2(qy·qz - qx·qw)],
     [2(qx·qz - qy·qw),  2(qy·qz + qx·qw),  1 - 2(qx² + qy²)]]
```

## 2. Pose Association

### Index-based (KITTI)
Pair poses by sequential line index. Use `min(len(gt), len(est))` pairs.

### Timestamp-based (TUM, EuRoC)
For each estimated pose, find the nearest unmatched ground-truth pose whose absolute timestamp difference is ≤ `max_diff` seconds. Each ground-truth pose may be matched at most once (bijective matching). Process estimated poses in order; for each, find the closest GT by timestamp among unmatched GT poses.

## 3. Umeyama Alignment

Find rotation R, translation t, and scale s minimizing:

    ‖T - s·R·S - t‖²

where S = source (estimated) positions, T = target (ground truth) positions, both as (N×3) matrices.

### Derivation

1. Centroids: μ_S = mean(S), μ_T = mean(T)
2. Centered sets: S_c = S - μ_S,  T_c = T - μ_T
3. Cross-covariance: W = (T_c)ᵀ S_c / N
4. SVD: W = U Σ Vᵀ  (Σ = diag of singular values D₁, D₂, D₃)
5. Reflection correction: S = I₃; if det(U)·det(Vᵀ) < 0, set S₃₃ = -1
6. Rotation: R = U S Vᵀ
7. Scale (Sim3): s = tr(Σ·S) / σ²_S,  where σ²_S = ‖S_c‖²_F / N = Σᵢ‖S_c[i]‖² / N
8. Scale (SE3): s = 1.0
9. Translation: t = μ_T - s·R·μ_S

### Applying Alignment

    aligned[i] = s · R · source[i] + t

## 4. RANSAC Robust Alignment

Parameters: `threshold`, `max_iterations`, `min_samples` (default 3), `seed`.

**Use `numpy.random.RandomState(seed)` for deterministic random sampling.**

### Procedure

1. For each iteration (up to `max_iterations`):
   a. Sample `min_samples` correspondence indices uniformly at random (without replacement)
   b. Compute Umeyama alignment on the sampled subset
   c. Apply alignment to ALL source points
   d. Compute per-point errors: ‖target[i] - aligned_source[i]‖
   e. Classify inliers: points where error < `threshold`
2. Keep the iteration with the most inliers
3. Recompute Umeyama alignment using ALL inlier points from the best iteration
4. Return (R, t, s, inlier_mask)

If the best inlier count is less than `min_samples`, fall back to aligning all points and mark all as inliers.

## 5. Error Metrics

### ATE (Absolute Trajectory Error)

Per-point errors after alignment: e[i] = ‖gt[i] - aligned_est[i]‖

Statistics:
- `rmse` = √(mean(e²))
- `mean` = mean(e)
- `median` = median(e)
- `std` = std(e)
- `max` = max(e)
- `min` = min(e)
- `num_poses` = number of evaluated poses
- `scale` = recovered scale factor

### RPE (Relative Pose Error — translational)

For consecutive pose pairs i = 0, ..., N-2:
- Δgt[i] = gt[i+1] - gt[i]     (forward difference)
- Δest[i] = aligned_est[i+1] - aligned_est[i]
- rpe[i] = ‖Δgt[i] - Δest[i]‖

Statistics:
- `rpe_rmse` = √(mean(rpe²))
- `rpe_mean` = mean(rpe)
- `rpe_median` = median(rpe)
- `rpe_max` = max(rpe)
- `rpe_num_pairs` = N-1

## 6. Pipeline Behavior

- Parse trajectories according to `--format`
- Associate poses (index-based for KITTI, timestamp-based otherwise)
- If `--robust`: run RANSAC alignment, then compute ATE on **inlier poses only**
- Otherwise: run standard Umeyama alignment, compute ATE on all matched poses
- If `--rpe`: compute RPE on the same (possibly inlier-filtered) poses and merge into output
- Write all metrics to `--output` as JSON

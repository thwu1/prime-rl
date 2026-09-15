Create a Visual SLAM trajectory evaluation pipeline at `/app/slam_eval/` that compares estimated camera trajectories against ground truth. The pipeline must parse three benchmark formats (KITTI, TUM, EuRoC), perform SVD-based trajectory alignment in SE(3) and Sim(3), support RANSAC-based robust alignment with outlier rejection, and compute both Absolute Trajectory Error (ATE) and translational Relative Pose Error (RPE). A mathematical specification covering alignment algorithms, format conventions, and metric definitions is at `/app/spec.md`. Synthetic test datasets are at `/app/data/`.

You must design the module architecture and implement all components from scratch. Only an empty `/app/slam_eval/__init__.py` is provided.

## CLI Interface

The main entry point must be `/app/slam_eval/pipeline.py`, invocable as:

```
python3 /app/slam_eval/pipeline.py \
    --format {kitti|tum|euroc} \
    --gt <path> --est <path> --output <path.json> \
    [--align {se3|sim3}] [--max_diff <float>] \
    [--robust] [--ransac_threshold <float>] \
    [--ransac_iterations <int>] [--ransac_seed <int>] \
    [--rpe]
```

Defaults: `--align se3`, `--max_diff 0.02`, `--ransac_threshold 0.2`, `--ransac_iterations 1000`, `--ransac_seed 42`. The process must exit with code 0 on success.

## Data Files

All at `/app/data/`:

- `kitti_gt.txt`, `kitti_est.txt` — KITTI format (12 space-separated floats per line: row-major 3x4 `[R|t]`), 150 poses each
- `tum_gt.txt`, `tum_est.txt` — TUM format (`timestamp tx ty tz qx qy qz qw`, scalar-last quaternion)
- `euroc_gt.csv` — EuRoC CSV ground truth (nanosecond timestamps, scalar-first quaternion order `qw,qx,qy,qz`)
- `euroc_est.txt` — EuRoC estimated trajectory in TUM format (seconds, scalar-last quaternions)
- `tum_outliers_est.txt` — TUM format with ~15 outlier-corrupted poses (every 10th)

## JSON Output Schema

ATE fields (always present in output JSON):

```json
{"rmse": float, "mean": float, "median": float, "std": float, "max": float, "min": float, "num_poses": int, "scale": float}
```

- `scale` is 1.0 for SE(3) alignment, or the recovered scale factor for Sim(3)
- `num_poses` is the number of poses used for metric computation

With `--robust`, add `"num_inliers": int` to the JSON. In robust mode, ATE metrics must be computed on the inlier pose subset only, so `num_poses` equals `num_inliers`.

With `--rpe`, merge RPE fields into the same JSON object (ATE fields remain present):

```json
{"rpe_rmse": float, "rpe_mean": float, "rpe_median": float, "rpe_max": float, "rpe_num_pairs": int}
```

`rpe_num_pairs` equals N-1 for N evaluated poses.

## Validation Targets

- **KITTI SE(3)**: ATE RMSE ~ 0.050, mean ~ 0.046, median ~ 0.044, max ~ 0.108, 150 poses, scale = 1.0
- **TUM SE(3)**: ATE RMSE ~ 0.066, mean ~ 0.061, max ~ 0.141, 150 poses, scale = 1.0
- **EuRoC Sim(3)** (`--align sim3 --max_diff 0.03`): ATE RMSE ~ 0.066, mean ~ 0.061, max ~ 0.148, recovered scale ~ 0.74, 150 poses
- **EuRoC SE(3)** (`--max_diff 0.03`): ATE RMSE > 0.8 (scale mismatch not recovered), scale = 1.0
- **TUM RANSAC** (`--robust`, `tum_outliers_est.txt`): robust ATE RMSE < 0.10, approximately 135 inliers from 150 total poses, `num_poses` == `num_inliers`; without `--robust` same data yields RMSE > 0.5
- **KITTI RPE** (`--rpe`): 149 consecutive pairs, RPE RMSE in [0.02, 0.12]; ATE fields also present with RMSE ~ 0.050 and 150 poses
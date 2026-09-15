`/app/` contains a multi-view 3D geometry pipeline: quaternion rotations (`rotation_utils.py`), depth unprojection and SE3 transforms (`geometry_utils.py`), 9D pose encoding (`pose_encoding.py`), COLMAP text I/O (`colmap_io.py`), and point cloud alignment (`alignment.py`). Quaternions use XYZW (scalar-last) internally; COLMAP stores WXYZ (scalar-first). Camera conventions follow OpenCV (x-right, y-down, z-forward).

Two COLMAP-format scenes are provided: `/app/data/` (clean ground truth — 10 3D points, 4 cameras) and `/app/data_noisy/` (same cameras and poses, but 3 of 10 point coordinates are replaced with far-off corrupted values).

The pipeline has silent numerical bugs across multiple modules — code runs without errors but produces wrong 3D results. `/app/alignment.py` contains two stubs: `estimate_similarity_transform` (returns identity placeholder) and `robust_estimate_similarity_transform` (raises NotImplementedError). Both must be implemented to correctly compute `(scale, rotation, translation)` aligning source points to target points; the robust variant must additionally return an `inlier_mask` boolean array and tolerate outlier-contaminated correspondences.

Debug all pipeline bugs, implement both alignment methods, and build a reconstruction quality evaluator. For each scene (`clean` and `noisy`), reconstruct the scene's 3D points via camera 1's depth map and align the result against the clean ground truth from `/app/data/`.

Store results in a SQLite database at `/app/results.db`:

- Table `quality_metrics` — one row per scene (`clean`, `noisy`):
  `scene_name TEXT PK, num_points INT, num_inliers INT, inlier_ratio REAL, rmse REAL, scale REAL`
  RMSE computed on inlier points only.

- Table `point_classifications` — one row per point per scene:
  `scene_name TEXT, point_id INT, gt_x REAL, gt_y REAL, gt_z REAL, rec_x REAL, rec_y REAL, rec_z REAL, residual REAL, is_inlier INT`
  PK: `(scene_name, point_id)`. Use robust alignment for `noisy` scene, basic alignment for `clean`.

Export aligned reconstructions as binary little-endian PLY point clouds to `/app/output/`:
- `clean.ply` — all aligned clean-scene points with per-vertex quality annotations
- `noisy_inliers.ply` — only inlier points from the noisy scene after robust alignment
Each PLY vertex must include properties: `x`, `y`, `z` (float64), `red`, `green`, `blue` (uint8), `residual` (float64), `is_inlier` (uint8).

Generate a JSON evaluation report at `/app/output/report.json` with per-scene metrics and per-point classifications. Use `jq` to extract from this report:
- `/app/output/outlier_ids.json` — JSON array of point IDs classified as outliers in the noisy scene
- `/app/output/metrics_summary.json` — JSON object with keys `clean_rmse`, `noisy_rmse`, `noisy_inlier_ratio`

Using the `sqlite3` command-line tool (not Python), create a view `outlier_analysis` in `/app/results.db` that joins `quality_metrics` and `point_classifications` to show per-scene outlier counts and mean outlier residuals. Export this view as CSV with headers to `/app/output/outlier_report.csv` using `sqlite3` CLI.
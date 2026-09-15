A COLMAP sparse reconstruction at `/app/scene/sparse/0/` (containing `cameras.bin`, `images.bin`, and `points3D.bin`) was prepared as input for 3D Gaussian Splatting training but produces severely degraded results — Gaussians diverge in size, rendered views appear scrambled, and geometric distortions are visible across multiple viewpoints. A COLMAP feature extraction database from the same capture session is available at `/app/scene/database.db` and contains ground-truth camera intrinsics and image-to-camera assignments.

Perform a comprehensive forensic audit of this reconstruction, repair all data integrity issues, evaluate its geometric fitness for 3DGS training, and produce scene configuration parameters. Corruptions span multiple data layers — camera parameters, pose representations, metadata mappings, and point cloud track topology — and include both format-level errors detectable via database cross-referencing and geometrically inconsistent observations that require spatial reasoning to identify (e.g., track entries referencing cameras from which a 3D point could not physically have been observed).

Produce:

1. Repaired reconstruction at `/app/repaired/cameras.bin`, `/app/repaired/images.bin`, `/app/repaired/points3D.bin` — all data corruptions corrected. Track entries representing physically impossible observations (where a 3D point projects to negative depth in an observing camera's coordinate frame) must also be excised. Repaired files must use the identical COLMAP little-endian binary format and preserve all uncorrupted data exactly.

2. Scene configuration at `/app/scene_config.json`:
```
{
  "normalization": {
    "center": [cx, cy, cz],
    "radius": float,
    "translate": [tx, ty, tz]
  },
  "quality_metrics": {
    "num_cameras": int,
    "num_images": int,
    "num_points": int,
    "behind_camera_entries_removed": int,
    "points_below_min_triangulation": int,
    "median_triangulation_angle_deg": float,
    "mean_track_length": float
  }
}
```
The `normalization` block follows the NeRF++ convention used by the 3DGS training pipeline: `center` is the centroid of all camera world positions (each computed as −R^T × t from the repaired extrinsics), `radius` is 1.1× the maximum Euclidean distance from `center` to any camera, and `translate` = −`center`. For `quality_metrics`: `behind_camera_entries_removed` counts track entries excised for negative camera-space depth; `points_below_min_triangulation` counts points whose maximum pairwise triangulation angle across all remaining observing cameras is below 2.0°.

3. Diagnostic report at `/app/diagnostic_report.json` with `issues` (list of objects each containing `type` (string category), `description` (string), and `affected_ids` (list of affected entity IDs)) and `total_issues` (integer count). Must cover all distinct corruption categories discovered.

Camera models present: 0 = SIMPLE_PINHOLE (f, cx, cy), 1 = PINHOLE (fx, fy, cx, cy). Quaternion convention is [w, x, y, z].
A multi-camera system recorded tracked feature correspondences across 5 calibrated cameras observing a static scene. The observation data at `/app/data/observations.json` contains 2D pixel coordinates for each (camera, point) pair, but approximately 10% of the observations are outliers from incorrect feature matching.

Camera intrinsic parameters (focal lengths `fx`, `fy` and principal point `cx`, `cy` for each camera) are at `/app/data/intrinsics.json`.

Implement a structure-from-motion pipeline that robustly recovers all camera extrinsic parameters (rotation and translation) and the 3D coordinates of the scene points from the noisy, outlier-contaminated observations. Camera 0 is the world reference frame (identity rotation, zero translation). The reconstruction is determined only up to a global scale factor.

Write the output to `/app/output/reconstruction.json` with the following schema:

```json
{
  "cameras": [
    {"camera_id": 0, "R": [[1,0,0],[0,1,0],[0,0,1]], "t": [0.0,0.0,0.0]},
    {"camera_id": 1, "R": [[...],[...],[...]], "t": [tx,ty,tz]},
    ...
  ],
  "points_3d": [
    {"point_id": 0, "xyz": [x, y, z]},
    ...
  ]
}
```

`R` is a 3x3 rotation matrix and `t` is a 3-element translation vector defining the world-to-camera transform: `P_cam = R @ P_world + t`.

## Evaluation Criteria

Your reconstruction will be verified against all of the following:

- **Completeness**: All 5 cameras (IDs 0–4) and at least 50 of the 60 scene points must appear in the output.
- **Rotation validity**: Every `R` must be orthonormal (R @ R^T ≈ I, tolerance 0.02) with determinant +1 (tolerance 0.02).
- **Reference frame**: Camera 0's `R` must be identity and `t` must be zero (tolerance 0.01).
- **Reprojection accuracy**: The median reprojection error across all matched observations must be below 1.5 pixels. Additionally, more than 80% of observations must have a reprojection error below 5 pixels.
- **Geometric accuracy**: After optimal similarity alignment (Umeyama/Procrustes) of your reconstruction to ground truth, the following must hold:
  - Mean camera rotation error < 5 degrees (geodesic angle between aligned and ground-truth rotation matrices).
  - Normalized mean camera position error < 15% (mean camera center error divided by mean ground-truth baseline distance).
  - Normalized 3D point RMSE < 5% (RMSE of aligned reconstructed points vs. ground-truth points, divided by scene extent).
An HDF5 file at `/app/data/scans.h5` contains five 3D point cloud scans of the same object captured under different rigid poses. Use `h5ls /app/data/scans.h5` or Python's `h5py` module to inspect the file's hierarchical structure and extract point coordinate data from the appropriate datasets.

A previous engineer's registration attempt is at `/app/pipeline/attempt.py`. It executes without errors but produces geometrically incorrect alignment transforms. Diagnose the deficiencies in this pipeline by analyzing both the code logic and the characteristics of the scan data, then produce correct registration results.

You may **not** use any dedicated point cloud registration library (`probreg`, `open3d.pipelines.registration`, PCL bindings, etc.). Implement or repair the registration using general-purpose numerical libraries (`numpy`, `scipy`, etc.).

Write `/app/output/transforms.json` containing a JSON object with keys `"T_1"` through `"T_4"`. Each value must be a 4×4 homogeneous transformation matrix represented as a list of 4 lists of 4 floats. Applying `T_i` to a point from scan *i* via `T_i @ [x, y, z, 1]` must yield coordinates aligned to scan 0's frame.

## Output requirements

Each transform matrix must satisfy all of the following:

- The bottom row of the 4×4 matrix must be `[0, 0, 0, 1]`.
- The 3×3 upper-left rotation block must be near-rigid: the cube root of the absolute value of its determinant must fall between 0.7 and 1.3.
- The angular error of the recovered rotation relative to the true generating rotation must be less than 5 degrees.
- The Euclidean error of the recovered translation relative to the true generating translation must be less than 0.3 units.
- After applying the transform to scan *i*, the median nearest-neighbor distance between the aligned points and scan 0's points must be less than 0.5 units.
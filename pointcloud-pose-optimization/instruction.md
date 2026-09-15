Eight overlapping 3D point cloud scans of a synthetic indoor environment are stored in a single HDF5 file at `/app/data/scans.h5`. The scans contain measurement noise.

Approximate initial pose estimates and a table of overlapping scan pairs are also provided in the same file.

Determine the rigid transformation for each scan that maps its local coordinate frame to a globally consistent common reference frame (scan 0's frame). The alignment must be globally consistent across all listed overlap pairs — not just sequential neighbors.

## Data

`/app/data/scans.h5` — HDF5 file with the following structure:

- `/scans/scan_000` through `/scans/scan_007` — datasets of shape `(N, 3)`, dtype float64, gzip-compressed 3D point clouds in each scan's local coordinate frame
- `/initial_poses` — dataset of shape `(8, 4, 4)`, dtype float64, approximate pose estimates (pose 0 is identity)
- `/overlap_pairs` — dataset of shape `(P, 2)`, dtype int32, scan index pairs with spatial overlap

## Output

Write results to `/app/output/result.h5` as an HDF5 file containing:

- A dataset named `poses` with shape `(8, 4, 4)` and dtype float64 — the estimated sensor poses
- An integer attribute `reference_scan` on the `poses` dataset with value `0`

Each pose `T_i` transforms homogeneous points from scan `i`'s local frame to the reference frame: `p_ref = T_i @ [p_local; 1]`.

## Acceptance criteria

- **Pose 0**: Must be the 4×4 identity matrix (it defines the reference frame).
- **Valid rigid transforms**: Every pose must have an orthogonal 3×3 rotation submatrix with determinant 1 and bottom row `[0, 0, 0, 1]`.
- **Per-pose translation accuracy**: Each pose's translation must be within 0.5 m of ground truth.
- **Per-pose rotation accuracy**: Each pose's geodesic rotation error must be below 0.15 rad.
- **Absolute trajectory error (ATE)**: RMS translation error across all 8 poses must be below 0.3 m.
- **Relative pose consistency**: For each consecutive pair `(i, i+1)` where `i = 0..6`, the relative transformation must have translation error below 0.6 m and rotation error below 0.2 rad compared to ground truth.
The file `/app/pose_graph.json` contains a pose graph with 12 nodes and 28 pairwise relative rotation measurements. Each edge stores the relative rotation R_j @ R_i^T between nodes i and j, corrupted by small Gaussian noise. The measurements use mixed formats: some are 3x3 rotation matrices, some quaternions (w,x,y,z), some axis-angle vectors, and some Euler angles (XYZ intrinsic). A rotation conversion library is provided at `/app/rotations_lib.py`.

Three of the edges are gross outliers — their measured rotations are completely wrong, not just noisy. Two anchor nodes have known ground-truth rotations (given in the `anchors` field).

Design and implement a rotation synchronization pipeline that recovers globally consistent absolute rotations for all 12 nodes while identifying and rejecting the outlier edges. Your system must compare at least two distinct strategies (e.g., different initializations, different optimization methods, or different outlier rejection schemes) and determine which performs better on this problem.

## Output specification

Write outputs to `/app/output/`:

- **`/app/output/rotations.json`** — JSON object mapping node index (string key `"0"` through `"11"`) to a 3x3 rotation matrix (list of 3 lists of 3 floats). All 12 nodes must be present. Every matrix must be a valid SO(3) element: orthogonal with determinant +1 (tolerance 1e-4). Anchor node rotations must match their ground-truth values exactly (tolerance 1e-4).

- **`/app/output/outliers.json`** — JSON list of `[i, j]` pairs identifying detected outlier edges. Each entry must be a list of exactly two integers.

- **`/app/output/report.json`** — JSON object documenting the strategy comparison with these required fields:
  - `strategy_a_name` (non-empty string): name of the first strategy
  - `strategy_b_name` (non-empty string): name of the second strategy (must differ from `strategy_a_name`)
  - `strategy_a_mean_residual_deg` (non-negative float): mean geodesic residual in degrees for strategy A
  - `strategy_b_mean_residual_deg` (non-negative float): mean geodesic residual in degrees for strategy B
  - `chosen_strategy` (string): must exactly match either `strategy_a_name` or `strategy_b_name`, and must correspond to the strategy with equal or lower mean residual
  - `outlier_threshold_deg` (positive float): the threshold used for outlier detection

## Evaluation criteria

Your solution will be evaluated against hidden ground-truth rotations and outlier labels:

- Each recovered rotation must be within **10 degrees** geodesic distance of the true rotation.
- The **mean** geodesic error across all 12 nodes must be below **5 degrees**.
- At least **2 of the 3** true outlier edges must be correctly detected.
- At most **2 false positive** outlier detections are allowed.
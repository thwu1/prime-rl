A buggy 2D Gauss-Newton/Levenberg-Marquardt optimizer for SE(2) pose graphs is at `/app/optimizer.py`. Test graphs are in `/app/graphs/`: `square_loop.g2o` (8-node clean loop with noisy odometry and a loop closure), `corrupted_loop.g2o` (same graph with additional outlier cross-loop edges). Ground truth poses are at `/app/graphs/ground_truth.txt` (format: `id x y theta`). Solver configs are at `/app/config_clean.yaml` and `/app/config_robust.yaml`.

Optimizer CLI: `python3 /app/optimizer.py --graph <g2o> --config <yaml> --output <file>` (also writes `<output>.report` JSON with convergence info).

## Deliverables

**Fixed `/app/optimizer.py`**: Find and fix the bugs so that on `square_loop.g2o` with `config_clean.yaml`, every optimized pose is within 0.2 m position error and 0.15 rad angle error of ground truth; on `corrupted_loop.g2o` with `config_robust.yaml`, within 0.5 m and 0.3 rad despite outlier edges. All output angles normalized to [-pi, pi]. Fixed vertices must remain unchanged. The `.report` JSON must contain: `iterations` (int), `initial_cost` (float), `final_cost` (float), `cost_history` (float array), `converged` (bool). The optimizer must converge on the clean graph with monotonically decreasing cost.

**Marginal covariance recovery tool** `/app/covariance.py`:

`python3 /app/covariance.py --graph <g2o> --poses <poses_file> --output <report.json>`

Assemble the Gauss-Newton Hessian (information matrix) at the given poses: H = sum over all edges of J_e^T * Omega_e * J_e. Extract the sub-block corresponding to free (non-fixed) vertices and invert to obtain the marginal covariance matrix. Output JSON:

- `poses`: dict mapping vertex ID (string) to `{"covariance": [[3x3 matrix]], "ellipse": {"semi_major": float, "semi_minor": float, "angle_rad": float}, "pos_trace": float}`
- `covariance_matrix_size`: int (dimension of the free Hessian block)

The uncertainty ellipse is derived from eigendecomposition of the 2x2 position sub-block of each pose's marginal covariance: semi-axes = sqrt(eigenvalues), orientation = atan2 of the principal eigenvector. `pos_trace` = sigma_x^2 + sigma_y^2. Fixed vertices get zero covariance and zero ellipse parameters.

**Edge consistency analyzer** `/app/consistency.py`:

`python3 /app/consistency.py --graph <g2o> --poses <poses_file> --threshold <float> --output <report.json>`

For each edge in the graph, compute the SE(2) error between the predicted relative pose (from current estimates) and the measurement, then compute the chi-squared statistic: chi2 = e^T * Omega * e where Omega is the edge's information matrix. An edge is consistent if chi2 <= threshold (the threshold is the chi-squared critical value with 3 degrees of freedom for SE(2)). Output JSON:

- `edges`: list of `{"from": int, "to": int, "chi_squared": float, "consistent": bool}`
- `num_consistent`: int
- `num_inconsistent`: int

**Trajectory evaluation tool** `/app/evaluate.py`:

`python3 /app/evaluate.py --estimated <poses_file> --reference <poses_file> --output <report.json>`

Output JSON: `ate_rmse` and `ate_max` (Euclidean position errors across matched poses), `rpe_trans_mean` and `rpe_rot_mean` (translational and rotational components of relative pose error computed using proper SE(2) composition: error = T_ref_rel^{-1} * T_est_rel over consecutive pose pairs), `num_poses`.

**End-to-end pipeline** `/app/pipeline.sh`:

`bash /app/pipeline.sh <g2o_file> <config_yaml> <output_dir>`

Must produce in `<output_dir>/`: `optimized.txt` and `optimized.txt.report` (optimizer output), `graph.svg` (valid SVG visualization of pose-graph topology), `convergence.png` (cost vs iteration plot), `evaluation.json`, `covariance.json`, `consistency.json`.
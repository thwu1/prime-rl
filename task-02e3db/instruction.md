A synthetic SE(3) pose graph dataset at `/app/pose_graph.json` contains 40 camera poses on a circular trajectory with 39 sequential odometry edges (high-confidence, weight 30000), 9 loop closure edges connecting non-adjacent poses (weight 3), and 2 outlier loop closure edges with grossly incorrect relative-pose measurements (weight 3). The initial pose estimates (`init_poses`) have been corrupted by accumulated odometry drift.

SE(3) Lie group utilities at `/app/se3.py` provide exponential/logarithm maps, composition, inversion, and right-perturbation retraction. These are correct and must not be modified.

Complete the solver stub at `/app/pgo_solver.py` to jointly optimize all non-fixed camera poses given the noisy relative-pose measurements across all edges. Pose 0 is fixed and must not be modified during optimization. The solver must be robust to the outlier loop closure edges.

Requirements:
- The optimized trajectory must recover the true camera poses to within 0.10 m maximum translation error and 1.0 degree maximum rotation error across all non-fixed poses.
- Disabling robust estimation (setting `huber_scale=inf`) must produce at least 2x worse translation error than enabling it, confirming effective outlier rejection.

Write the optimized trajectory to `/app/result_trajectory.json` by running the solver's `__main__` block.
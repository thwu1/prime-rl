`/app/data/simulation.g2o` contains a 2D pose graph in the G2O format (specification at `/app/data/format_spec.txt`) from a simulated robot traversing a circular path. The graph consists of 40 pose vertices, sequential odometry edges, several valid loop closure edges, and 3 outlier loop closure edges arising from incorrect scan matches between geometrically distant locations. The initial vertex positions reflect accumulated odometry drift and are inconsistent with the loop closure constraints.

Implement `/app/optimizer.py` that reads the pose graph, optimizes it using iterative nonlinear least squares on the SE(2) manifold with robust outlier handling, and writes:

- `/app/output/optimized_poses.txt` — one line per vertex: `id x y theta`
- `/app/output/edge_residuals.txt` — one line per edge: `id_from id_to chi_squared`
- `/app/output/summary.txt` — must contain lines `initial_chi2: <value>`, `final_chi2: <value>`, `num_outliers: <count>` (outlier = edge with post-optimization chi-squared exceeding 1000)

Run with: `python3 /app/optimizer.py`
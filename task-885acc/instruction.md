A 2D SLAM back-end dataset is stored in the SQLite database `/app/pose_graph.db`. The database schema, binary BLOB format for the information matrices, and SE(2) measurement conventions are documented in `/app/SPEC.md`.

The dataset contains 20 robot poses (ids 0-19) from an out-and-back traversal along the x-axis: a forward leg (nodes 0-9, heading ~0) and a return leg (nodes 10-19, heading ~pi). The poses are connected by 19 odometry edges and 7 loop-closure edges. Initial pose estimates are from dead-reckoning and have accumulated drift. Some loop-closure edges are incorrect data associations that, if naively trusted, will badly distort the trajectory.

An SE(2) computation library is provided as C source at `/app/tools/` with a Makefile. Compile it to produce a shared library for use in your optimizer.

Produce globally consistent optimized poses that satisfy the valid constraints while preventing incorrect loop closures from corrupting the result. Write output to `/app/result.json` as a JSON array of objects, one per node, each with numeric fields `id`, `x`, `y`, `theta`. All values must be finite.

## Requirements

- **Gauge anchor**: Fix node 0 at approximately (0, 0, 0) — it must remain within 0.1 of the origin in x, y, and theta.
- **Trajectory shape**: The optimized trajectory must preserve the out-and-back structure. The x-extent (max x minus min x) must exceed 30 m. All nodes must satisfy |y| < 6 m.
- **Heading consistency**: Forward-leg nodes (0-9) must have heading within 0.5 rad of 0. Return-leg nodes (10-19) must have heading within 0.5 rad of pi.
- **Loop-closure satisfaction**: At least 4 of the 7 loop-closure edges must be well-fitted, with translational residual (the norm of the position error in the local frame of the from-node, compared to the measured relative transform) below 2.0 m.
- **True co-location**: The true loop closures pair nodes that revisit the same location from opposite directions: (19,0), (17,2), (15,4), (13,6), (11,8). After optimization, at least 3 of these 5 pairs must be within 3 m of each other.
- **Outlier rejection**: The dataset contains two spurious loop closures. Specifically, nodes 14 and 1 must remain more than 10 m apart, and nodes 16 and 8 must remain more than 15 m apart.
- **Non-trivial optimization**: At least 5 nodes must move more than 0.01 m from their initial positions — the optimizer must actually modify the poses.
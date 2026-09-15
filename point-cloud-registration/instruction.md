`/app/scans.db` is a SQLite database containing four 3D point cloud registration scenarios of increasing difficulty. Use the `sqlite3` CLI tool or Python's `sqlite3` module to inspect the database schema — each scenario has source and target point clouds stored as individual point rows across related tables, along with scan metadata (noise level, outlier ratio, overlap ratio). You will need to write appropriate SQL queries to extract the point cloud data and join it with scan metadata.

`/app/pipeline.toml` contains registration pipeline configuration including algorithm parameters (iteration limits, convergence tolerance, scale estimation settings) and per-scenario outlier weights. Parse this TOML file to obtain all settings for your implementation.

Implement a probabilistic point cloud registration system that recovers the rotation matrix R, translation vector t, and scale factor s for each scenario, such that `target ≈ s * R @ source + t`. The scenarios involve varying amounts of Gaussian noise, uniform outlier contamination, and partial overlap between point clouds.

Write results to a new SQLite database at `/app/results.db`. Create a `transformations` table with the following schema:

- `scenario` (TEXT PRIMARY KEY) — scenario name matching the scan name
- `r11`, `r12`, `r13`, `r21`, `r22`, `r23`, `r31`, `r32`, `r33` (REAL) — 3×3 rotation matrix elements in row-major order
- `tx`, `ty`, `tz` (REAL) — translation vector components
- `scale` (REAL) — scale factor

Constraints:
- Do NOT use existing point cloud registration libraries (probreg, pycpd, open3d.pipelines.registration, etc.). Implement the registration algorithm yourself.
- The recovered rotation matrix must be a proper rotation (orthogonal, determinant +1).
- Your algorithm must handle all four scenarios including outlier-contaminated and partial-overlap cases.
- Read algorithm parameters and outlier weights from `/app/pipeline.toml` — do not hardcode configuration values.
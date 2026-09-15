A 3D rotation processing pipeline at `/app/` routes six core rotation conversion functions (`quaternion_to_matrix`, `matrix_to_quaternion`, `axis_angle_to_matrix`, `matrix_to_euler_angles`, `geodesic_distance`, `slerp`) to one of three backend libraries (`lib_alpha.py`, `lib_beta.py`, `lib_gamma.py`). The routing configuration is at `/app/pipeline.json`. NDJSON error logs from the last production run are at `/app/logs/pipeline_errors.ndjson` (one JSON object per line). A SQLite database at `/app/rotations.db` holds ground-truth test data in tables `test_rotations`, `test_geodesic`, and `test_slerp`; the `benchmark_results` table exists but is empty. A benchmark runner at `/app/run_benchmark.py` can evaluate any library against this database.

The pipeline is producing incorrect results: every function is currently routed to a backend whose implementation contains a mathematical flaw for that specific function. Each library has a different subset of bugs; no library is entirely correct or entirely broken.

Produce:

1. **`/app/audit_report.json`** -- JSON with three top-level keys:
   - `"bug_analysis"`: keyed by function name, each containing `"correct_libraries"` (list), `"flawed_libraries"` (list), `"root_cause"` (string, at least 50 characters, explaining the specific mathematical error in the flawed implementations), and `"affected_categories"` (list of rotation test categories from the database where the bug manifests).
   - `"propagation_analysis"`: keyed by descriptive label, each value a string explaining how a bug in one function cascades through dependent conversions or pipeline chains defined in `pipeline.json`.
   - `"pipeline_issues"`: keyed by function name, each explaining the current flawed routing and the correct alternative(s).

2. **`/app/rotation_service.py`** -- A standalone Python module that must NOT import from `lib_alpha`, `lib_beta`, or `lib_gamma`. Must export 14 functions: the 6 core functions plus `standardize_quaternion`, `axis_angle_to_quaternion`, `quaternion_to_axis_angle`, `matrix_to_axis_angle`, `euler_angles_to_matrix`, `rotation_6d_to_matrix`, `matrix_to_rotation_6d`, and `random_rotation_matrix`. Every function must produce numerically correct results (max error < 1e-8 on the benchmark suite).

3. **`/app/pipeline_fixed.json`** -- Same structure as `/app/pipeline.json` but with every function routed to a non-flawed backend.
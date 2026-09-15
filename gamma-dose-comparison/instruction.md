The directory `/app/reference/` contains incomplete fragments extracted from a radiation therapy dose comparison system. Study these materials to understand the gamma index metric, then build a working toolkit with a C acceleration layer.

**C Shared Library**

`/app/accel/shell_kernel.c` must implement N-sphere shell coordinate generation. Export these C functions:

- `int shell_count_2d(double radius, double max_gap)` — number of points for a 2D shell
- `int shell_count_3d(double radius, double max_gap)` — number of points for a 3D shell
- `void shell_1d(double distance, double* x, int* n)` — fills `x` with 1D shell points, sets `*n`
- `void shell_2d(double radius, double max_gap, double* x, double* y, int* n)` — 2D circle points
- `void shell_3d(double radius, double max_gap, double* x, double* y, double* z, int* n)` — 3D sphere points

At distance zero, all functions produce a single origin point. Points must lie on the N-sphere surface at the specified radius. Maximum nearest-neighbor Euclidean gap must not exceed the gap parameter. Caller allocates output arrays sized by the count functions (1D always needs at most 2 elements).

`/app/Makefile` must compile the C source into `/app/accel/libshell.so`. Required targets: `all` (default, builds library), `lib` (alias), `clean` (removes compiled artifacts).

**Python Modules**

`/app/gamma.py` must export:

- `calculate_shell_coordinates(distance, num_dimensions, distance_step_size)` — loads `/app/accel/libshell.so` via `ctypes`, delegates to the C functions, returns a tuple of `num_dimensions` numpy arrays.

- `gamma(axes_reference, dose_reference, axes_evaluation, dose_evaluation, dose_percent_threshold, distance_mm_threshold, lower_percent_dose_cutoff=20, interp_fraction=10, max_gamma=None, local_gamma=False, global_normalisation=None)` — numpy array shaped like `dose_reference`. Points below the dose cutoff yield NaN. `max_gamma` caps values. Grids may differ between reference and evaluation.

`/app/qa_report.py` must export:

- `generate_qa_report(reference_path, evaluation_path, axes_path, criteria_path)` — runs gamma analysis, persists results to SQLite at `/app/results.db`, returns a dict with keys: `pass_rate` (float, 0-100), `mean_gamma` (float), `max_gamma` (float), `points_evaluated` (int), `points_passing` (int), `passed` (bool).

**SQLite Schema** (`/app/results.db`, table `sessions`):

| Column | Type | Constraint |
|---|---|---|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| session_name | TEXT | UNIQUE NOT NULL |
| created_at | TEXT | NOT NULL (ISO 8601) |
| pass_rate, mean_gamma, max_gamma | REAL | NOT NULL |
| points_evaluated, points_passing | INTEGER | NOT NULL |
| passed | INTEGER | NOT NULL (0 or 1) |

`session_name` derives from the reference file basename without extension. Existing entries are replaced on conflict.

Data files in `/app/data/`: axes as JSON `{"axes": [[...], ...]}`, dose grids as whitespace-delimited text, criteria as JSON with `dose_percent_threshold`, `distance_mm_threshold`, `pass_rate_threshold`, `lower_percent_dose_cutoff`.

Only numpy and scipy may be used as external dependencies (ctypes, sqlite3, json are stdlib). The reference fragments are incomplete and may contain errors. Correctness is defined by `/tests/test_state.py`.

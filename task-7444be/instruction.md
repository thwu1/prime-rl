A Generalized Moving Peaks Benchmark (GMPB) is provided as C source code at `/app/gmpb_native/`. The GMPB generates dynamic fitness landscapes composed of cone-shaped peaks whose positions, heights, and widths change periodically. The fitness at any point is `f(x) = max_i { h_i - w_i * ||x - c_i|| }`. See `/app/gmpb_native/gmpb.h` for the full C API specification.

Build the GMPB shared library from source using the Makefile at `/app/gmpb_native/Makefile`. The Makefile has a build issue that must be diagnosed and fixed.

Write a complete Python ctypes wrapper at `/app/gmpb.py` that loads the compiled `/app/gmpb_native/libgmpb.so` and provides a `GMPB` class with the interface documented in the stub at `/app/gmpb_bridge_stub.py`. The wrapper must handle opaque C pointer lifecycle, array marshalling between numpy and C, and proper error detection.

Implement a dynamic optimization algorithm in `/app/optimizer.py` that exports a function `run_optimizer(gmpb)` taking a `GMPB` instance and returning the offline error (float). Offline error is the mean current error over all evaluations, where current error is the gap between the global optimum and the best fitness found so far in the current environment. The GMPB resets best-found tracking at each environment change.

Store per-environment tracking data in a SQLite database at `/app/results.db`. The database must contain a table `env_results` with the schema:

```sql
CREATE TABLE env_results (
    instance TEXT NOT NULL,
    env_id INTEGER NOT NULL,
    mean_error REAL NOT NULL,
    best_found REAL NOT NULL,
    PRIMARY KEY (instance, env_id)
);
```

The offline error for each instance must be computable via: `SELECT AVG(mean_error) FROM env_results WHERE instance = ?`

Your optimizer must achieve competitive offline error on three problem instances:

| Instance | num_peaks | dimension | change_frequency | shift_severity | num_environments | seed |
|----------|-----------|-----------|-----------------|----------------|-----------------|------|
| F1       | 10        | 5         | 5000            | 1.0            | 30               | 42   |
| F2       | 10        | 5         | 1000            | 1.0            | 30               | 123  |
| F3       | 10        | 10        | 5000            | 2.0            | 30               | 456  |

Performance thresholds: F1 offline error < 12.0, F2 < 15.0, F3 < 18.0.

Write results to `/app/results.json` with format: `{"F1": {"offline_error": <float>}, "F2": {"offline_error": <float>}, "F3": {"offline_error": <float>}}`
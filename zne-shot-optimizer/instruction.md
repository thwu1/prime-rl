A quantum error mitigation (QEM) system at `/app/` has two execution paths that must both produce correct results.

**Benchmarking Pipeline** (`make -C /app pipeline` → `/app/report.json`): A Make-orchestrated pipeline that extracts scenario configurations from a SQLite calibration database, evaluates three extrapolation methods across six noise scenarios in Python, and post-processes results via jq. The pipeline produces incorrect results due to interacting bugs across the SQL, Python, and jq layers.

**ZNE Optimization Analysis** (`make -C /app analysis` → `/app/results.json`): Reads test configurations from `/app/problems.json` and evaluates them through `/app/zne_optimizer.py`, which currently contains only stub implementations that raise `NotImplementedError`. You must implement all functions according to their docstrings. The analysis script also depends on a function in `/app/noise_model.py` that does not currently exist.

The system is correct when:

- Both `make -C /app pipeline` and `make -C /app analysis` complete without errors
- Scenario extraction faithfully reproduces database values (e.g., S3 asymptote = 0.15, S1 asymptote = 0.0)
- Exponential extrapolation recovers ideal values to <1e-5 error for pure exponential noise, including negative values and nonzero asymptotes
- Richardson extrapolation is exact (floating-point tolerance) for polynomial noise of degree ≤ n−1
- Shot allocation sums exactly to the total budget for all scenarios
- Best method per scenario corresponds to the one with lowest extrapolation error
- Improvement ratios in the report are ≥ 1
- Both `/app/report.json` and `/app/results.json` contain correct values

Run `make -C /app all` to execute both paths.
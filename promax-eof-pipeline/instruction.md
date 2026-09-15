A climate EOF (Empirical Orthogonal Function) analysis pipeline at `/app/` is incomplete and produces incorrect results. The pipeline decomposes gridded sea surface temperature anomalies stored in NetCDF format and applies rotated factor analysis to the leading modes.

**Layout:**
- `/app/run_analysis.py` — entry point (imports from `/app/pipeline/`)
- `/app/pipeline/` — modules: `preprocess.py`, `decompose.py`, `rotate.py`, `postprocess.py`
- `/app/climate_data.nc` — input dataset (NetCDF4 with CF conventions; use `ncdump -h` to inspect structure and metadata)
- `/app/task_config.json` — analysis parameters
- `/app/reference/` — correct reference outputs (`.npy` files)
- `/app/results/` — output directory

The rotation module (`/app/pipeline/rotate.py`) is a stub — `varimax_rotation()` and `promax_rotation()` raise `NotImplementedError` and must be implemented from scratch following the algorithm specifications in their docstrings. Additionally, three other pipeline modules contain independent numerical bugs that cause outputs to diverge from the reference. Fix all issues so that `python3 /app/run_analysis.py` produces 11 `.npy` files in `/app/results/` matching `/app/reference/` within floating-point tolerance.
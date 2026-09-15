Reference type curve data for high-conductivity aquifer slug test analysis is provided at `/app/reference/type_curves.json`. Each entry maps dimensionless time (`td`) to normalized head deviation (`wd = w/H₀`) for a dimensionless damping coefficient `CD`. The data spans CD from 0.25 to 10.0. A critical CD threshold separates oscillatory responses from monotonically decaying ones.

The physical relationship between dimensionless time and real time is `td = α·(t − t₀)` where `α = √(g/Le)`, g = 9.80665 m/s², Le is the effective water column length (meters), and t₀ is the test start time offset (seconds).

Create `/app/slug_test_analyzer.py` implementing three subcommands:

**`generate`**: `python3 /app/slug_test_analyzer.py generate --cd <float> --td-max <float> --dt <float> --output <path>`
- Outputs CSV with header `td,wd` at points `td = 0, dt, 2·dt, …, td_max`
- Must reproduce reference data within absolute tolerance 5×10⁻⁴
- Must handle CD ∈ [0.1, 50.0] and td up to 200.0
- Must be numerically stable for large CD·td products

**`fit`**: `python3 /app/slug_test_analyzer.py fit --data <path> --output <path>`
- Input CSV with header `time,normalized_head` (real time in seconds, H(t)/H₀)
- Simultaneously recovers CD, Le, α, and t₀ from the data
- Output JSON: `{"cd": <float>, "le": <float>, "alpha": <float>, "t0": <float>}`
- CD accuracy on clean data: 2% relative error for CD > 0.5; 0.02 absolute for CD ≤ 0.5
- CD accuracy on noisy data (Gaussian σ ≤ 0.01): 5% relative error for CD > 0.5
- Le accuracy: 2% relative error (clean), 5% (noisy)
- Must handle data with Gaussian noise σ ≤ 0.01

**`batch`**: `python3 /app/slug_test_analyzer.py batch --config <path> --output-dir <path>`
- Config JSON: `{"scenarios": [{"name": "<string>", "data_file": "<path>"}, ...]}`
- Writes `<name>.json` fit results into the output directory for each scenario

All subcommands exit 0 on success, non-zero on error. The tool must derive the underlying mathematical model from the reference data and physical context — it is not provided explicitly.

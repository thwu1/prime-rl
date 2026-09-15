Complete the `ZNEShotOptimizer` class at `/app/optimizer.py` and build a validation pipeline against the reference database at `/app/reference_data.db`.

## Context

The `/app/` directory contains a quantum simulation framework:
- `/app/hamiltonian.py` — Hamiltonian decomposition into qubitwise-commuting groups
- `/app/simulator.py` — Noisy measurement sampling under a depolarizing noise model with configurable scale factors
- `/app/optimizer.py` — Skeleton class with seven unimplemented methods
- `/app/reference_data.db` — SQLite database with worked examples for each optimizer component

## Optimizer

Implement all seven methods in `/app/optimizer.py`. The optimizer performs zero-noise extrapolation (ZNE) — estimating the noiseless expectation value of a Hamiltonian from measurements taken at multiple noise amplification levels — with variance-optimal shot allocation across noise levels and observable groups.

Explore the reference database schema and data to understand the mathematical relationships each method must satisfy. Correctness criteria:

- Extrapolation coefficients and extrapolated values must match the reference examples
- Variance estimation must properly account for covariance between co-measured Pauli terms within a commuting group
- Shot allocation must produce integer counts that sum to the total budget with every cell receiving at least 1 shot, while minimizing the overall ZNE estimation variance
- The adaptive multi-round procedure must achieve lower mean squared error than uniform allocation

## Validation Pipeline

Create an executable script at `/app/extract_and_validate.sh` that uses `sqlite3` and `jq` to extract and process data from `/app/reference_data.db`, validates the optimizer against those references, and writes `/app/validation_report.json`.

The report must be a JSON object keyed by table name (`coefficient_examples`, `extrapolation_examples`, `variance_formula_examples`, `group_variance_examples`, `allocation_examples`), each mapping to `{"total": <int>, "passed": <int>, "status": "pass"|"fail"}`, plus a top-level `"all_passed": true` when every table passes (tolerance 1e-6).
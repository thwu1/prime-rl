A partial analysis script at `/app/analyze.py` uses the Qualtran library (pre-installed, v0.7.0) to evaluate surface-code resource requirements for factoring RSA moduli via Shor's algorithm. Configuration parameters and the search space are specified in `/app/targets.json`. The script currently crashes and only evaluates a single cost-model configuration.

Extend or rewrite the analysis to produce `/app/deployment_plan.json` with the following structure:

**Per-modulus entries** (keyed by modulus as string):

- **`algorithm_costs`**: `{n_t, n_ccz, algo_qubits, bitsize}` — intrinsic QEC gate counts (using `ts_per_rotation=0`, excluding rotation synthesis overhead) and total algorithm qubits reflecting the circuit's full register allocation (exponent + work registers).

- **`pareto_frontier`**: Non-dominated points on the (phys_qubits, error) plane evaluated across every (cost_model × code_distance) combination specified in `targets.json`. Point A dominates point B iff `A.phys_qubits ≤ B.phys_qubits` AND `A.error ≤ B.error` with at least one strict inequality. Each point: `{model, code_distance, phys_qubits, error, duration_hr}`. Sorted ascending by `phys_qubits`.

- **`recommended_config`**: The feasible configuration with minimum `phys_qubits`, where feasible means `error < error_budget` AND `duration_hr < max_duration_hr` (from `targets.json`). Same fields as Pareto points. `null` if nothing qualifies.

**Top-level `scaling` entry**:

- **`toffoli_counts`**: Symbolic Toffoli/CCZ count from a symbolic `RSAPhaseEstimate` evaluated at each bitsize in `scaling_bitsizes`, substituting all remaining free symbolic parameters with 1. Keyed by bitsize as string, integer values.
- **`fit_exponent`** and **`fit_coefficient`**: From a power-law fit `Toffoli ≈ a·n^b` via log-log ordinary least-squares regression on the `toffoli_counts` data points.
- **`predicted_2048`**: Integer Toffoli count prediction at `n=2048` using the fitted model.
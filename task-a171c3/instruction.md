The `qpe-toolbox` library (v1.1.0) is pre-installed. An initial QPE analysis for a 4-qubit Heisenberg spin chain has been left at `/app/initial_analysis.py`, with its output in `/app/initial_results/analysis.json`.

The analysis has been flagged for review:

- The 2-qubit validation shows a QPE-extracted energy that deviates far from the DMRG reference
- The error bound values do not agree with the library's built-in estimation utilities
- Only one QPE approach was evaluated; the library supports additional methods

Audit the analysis, correct the errors, and produce an extended multi-method comparison. Write all outputs as JSON files under `/app/results/`:

- `spectrum.json` — Eigenvalue spectrum and DMRG ground-state energy for the 4-qubit model, with fields `n_qubits`, `n_terms`, `eigenvalues` (sorted list), and `ground_energy_dmrg`
- `lcu_parameters.json` — LCU decomposition parameters (`lambda_norm`, `n_lcu_terms`, `n_auxiliary_qubits`, `weights`) and oracle verification results (`select_is_unitary`, `reflection_is_involution`, `select_energy_ratio`)
- `corrected_bounds.json` — Corrected energy error bounds keyed by string phase-register size (`"2"` through `"8"`), each containing `lcu_error` and `trotter_resolution` (with `size_interval=2`)
- `gate_counts.json` — Gate counts for a Trotter-based QPE circuit on the 4-qubit model with 2 phase qubits and 2 time steps (first-order decomposition), broken into `1qb`, `2qb`, `3+qb`, and `total_entangling`
- `qpe_validation.json` — An actual QPE simulation on the 2-qubit Heisenberg model with 2 phase qubits, producing `theta`, `energy`, `ground_energy`, `lambda_norm`, `error_bound`, and `energy_matches` (boolean)
- `recommendation.json` — For a target precision of 0.8, report `lcu_min_phase_qubits` and `trotter_min_phase_qubits`, plus `recommended_method` and `justification`
`/app/simulator.py` implements a density matrix quantum circuit simulator with per-gate depolarizing noise. `/app/circuits.py` provides circuit constructors (GHZ, mirror, identity, random Clifford, parametric). `/app/observables.py` defines standard observables (ground-state projector, Pauli Z, ZZ correlator).

Implement `/app/zne.py` — a complete Zero-Noise Extrapolation (ZNE) error mitigation system. ZNE works by executing quantum circuits at artificially increased noise levels via circuit folding, then extrapolating the measured expectation values back to the zero-noise limit.

Required exports in `/app/zne.py`:

- `fold_global(circuit, scale_factor)` — Global folding: returns C·(C†·C)^((s-1)/2) for odd integer s. Must raise `ValueError` for even or non-positive scale factors.
- `fold_gates(circuit, scale_factor)` — Per-gate folding: each gate G becomes G·(G†·G)^((s-1)/2).
- `richardson_extrapolate(scale_factors, values)` — Lagrange interpolation of the (scale_factor, value) pairs evaluated at λ=0. Must raise `ValueError` on length mismatch.
- `polynomial_extrapolate(scale_factors, values, order)` — Least-squares polynomial fit of the given degree, evaluated at λ=0. Must raise `ValueError` when order ≥ len(data).
- `exponential_extrapolate(scale_factors, values, asymptote=None)` — Fit f(λ)=a+b·exp(c·λ), return f(0). When `asymptote` is supplied, fix a to that value.
- `adaptive_extrapolate(scale_factors, values)` → `(float, str)` — Select the best extrapolation via leave-one-out cross-validation among `'richardson'`, `'polynomial_1'`, `'polynomial_2'`, `'exponential'`. Return (extrapolated_value, selected_method_name).
- `execute_with_zne(circuit, n_qubits, observable, noise_level, scale_factors=[1,3,5], extrapolation='richardson', fold_method='global')` — Full pipeline: fold at each scale factor, simulate with noise, extrapolate. `extrapolation` accepts `'richardson'`, `'polynomial_1'`, `'polynomial_2'`, `'exponential'`, or `'adaptive'`. `fold_method` accepts `'global'` or `'gates'`.

Import `Gate`, `Circuit`, `simulate`, and `expectation_value` from `simulator`. Use `Gate.dagger()` for gate adjoints. Study the gate representations in `simulator.py` (including `S_DAG` and `T_DAG` entries in the `GATES` dict) before implementing folding.
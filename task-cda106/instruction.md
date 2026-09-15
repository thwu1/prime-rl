Implement a density matrix simulator for quantum entanglement distillation with LOCC (Local Operations and Classical Communication) constraints, then use it to design distillation circuits that exceed specified fidelity thresholds for four noise scenarios.

## Background

In a quantum network, noisy Bell pairs are described by Bell-diagonal states:

    ρ = a|Φ+⟩⟨Φ+| + b|Ψ+⟩⟨Ψ+| + c|Φ-⟩⟨Φ-| + d|Ψ-⟩⟨Ψ-|

where |Φ±⟩ = (|00⟩ ± |11⟩)/√2 and |Ψ±⟩ = (|01⟩ ± |10⟩)/√2. Distillation uses N noisy pairs (2N qubits) to produce one high-fidelity pair. Qubits are split between Alice (0..N-1) and Bob (N..2N-1). Pairs are numbered outside-in: pair i = (qubit i, qubit 2N-1-i). The output pair is always (qubit N-1, qubit N). Circuits must respect LOCC: two-qubit gates may only act within one party's qubits; classical communication (measurements, conditional gates) is unrestricted. A designated flag classical bit enables post-selection — only branches where flag=0 are kept.

## Deliverables

1. **`/app/engine.py`** — Complete the density matrix simulator by implementing all TODO functions in the skeleton at `/app/skeleton.py`. Required: `initialize_bell_pairs`, `apply_single_qubit_gate`, `apply_two_qubit_gate`, `measure_qubit`, `partial_trace`, `compute_fidelity`, `validate_locc`, `run_distillation`. The `Circuit` class, gate matrices, and Bell state constants are provided in the skeleton.

2. **`/app/circuits.py`** — Export a function `get_circuit(scenario_id)` that returns a `Circuit` object (from your engine module) for each scenario in `/app/scenarios.json`. Each circuit must be LOCC-valid and achieve post-distillation fidelity ≥ the scenario's threshold.

## Reference Files

- `/app/skeleton.py` — Function signatures, docstrings, `Circuit` class, gate/Bell-state constants
- `/app/scenarios.json` — Four noise scenarios with Bell-diagonal parameters, N, and fidelity thresholds
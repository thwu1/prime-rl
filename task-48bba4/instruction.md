A quantum circuit compilation workspace at `/app/` was set up to retarget quantum circuits for two QPU backends. The hardware specifications (`/app/hardware_specs.json`) define each backend's native gate set and qubit coupling topology. A Qiskit-based compilation pipeline (`/app/pipeline.py`) was run against a 5-qubit Heisenberg Trotter circuit (`/app/circuit.qasm`) and a 2-qubit target unitary (`/app/target_unitary.json`), but post-run validation (`/app/validation_report.json`) found multiple failures across the compiled outputs.

Diagnose the root causes of these validation failures and produce correct compilations that satisfy all criteria:

- Native gate set compliance for each target backend
- Coupling topology compliance (two-qubit gates only between physically connected qubit pairs)
- Unitary preservation within Hilbert-Schmidt distance < 0.01

Write results to `/app/results/`:
- `target_a_circuit.qasm` — 5-qubit circuit for Target A
- `target_b_circuit.qasm` — 5-qubit circuit for Target B
- `target_a_synth.qasm` — 2-qubit unitary synthesis for Target A
- `target_b_synth.qasm` — 2-qubit unitary synthesis for Target B
- `metrics.json` — keys `target_a_circuit`, `target_b_circuit`, `target_a_synth`, `target_b_synth`, each with `num_two_qubit_gates` (int) and `fidelity_distance` (float)
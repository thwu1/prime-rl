Build a quantum circuit compilation and verification pipeline at `/app/pipeline.py` that performs unitary synthesis and topology-constrained circuit compilation using the BQSKit quantum compiler framework.

## Inputs

- `/app/config.py` — Defines three 2-qubit target unitary matrices (iSWAP, √SWAP, magic basis change), two target gate sets (`cnot_u3` mapping to {CNOT, U3} and `cz_u3` mapping to {CZ, U3}), a linear-chain 4-qubit topology, and quality thresholds.
- `/app/input_circuit.qasm` — A 4-qubit OPENQASM 2.0 circuit with non-linear qubit connectivity (includes edges not present in the target topology).

## Requirements

**Unitary Synthesis**: For each of the 3 target unitaries and each of the 2 gate sets (6 total combinations), synthesize a quantum circuit that implements the target unitary using only gates from the specified set. Each synthesized circuit must achieve Hilbert-Schmidt distance below the configured threshold from its target and use at most 3 two-qubit gates. The Hilbert-Schmidt distance between unitaries U and V is `d(U,V) = 1 - |Tr(U†V)| / n` where n is the matrix dimension. Save each circuit as QASM in `/app/output/`.

**Topology-Constrained Compilation**: Compile `/app/input_circuit.qasm` to the linear-chain topology defined in the config. After compilation, every two-qubit gate in the output circuit must act only on adjacent qubits in the topology. The compiled circuit must be functionally equivalent to the original up to qubit permutation introduced by routing. Save the compiled circuit as QASM in `/app/output/`.

**Results**: Write `/app/results.json` containing:
- `"unitary_synthesis"` — list of 6 entries, each with: `target_name`, `gate_set`, `two_qubit_gate_count` (int), `total_gate_count` (int), `hs_distance` (float), `qasm_file` (relative path from `/app/`)
- `"circuit_compilation"` — dict with: `cnot_count_original` (int), `cnot_count_compiled` (int), `hs_distance` (float), `topology_valid` (bool), `qasm_file` (relative path from `/app/`)
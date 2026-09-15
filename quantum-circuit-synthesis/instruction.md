Quantum target unitaries are defined in `/app/unitaries.py` (`TARGETS` dict, as numpy arrays) with per-circuit maximum CNOT counts in `MAX_CNOTS`. Hardware constraints are in `/app/hardware.json`, specifying the native gate set and a qubit coupling graph for three-qubit circuits.

Write `/app/compile.py` to synthesize a quantum circuit for each target unitary. Each compiled circuit must:

- Use only the native gate set specified in the hardware configuration
- For three-qubit targets, have two-qubit gate connectivity compatible with the coupling graph
- Achieve Hilbert-Schmidt distance < 1e-3 from the target unitary (accounting for possible qubit relabelling from topology mapping)
- Not exceed the per-circuit CNOT threshold from `MAX_CNOTS`

Output each compiled circuit as a QASM 2.0 file at `/app/output/<name>.qasm` and write a summary to `/app/output/results.json` mapping each target name to `{"cnot_count": <int>, "distance": <float>, "num_qubits": <int>}`.
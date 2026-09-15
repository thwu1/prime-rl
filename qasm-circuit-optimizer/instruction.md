Several OpenQASM 2.0 quantum circuits are provided in `/app/circuits/`. Each implements a quantum operation using more two-qubit (CX) gates than necessary.

Create `/app/optimize.py` that takes a QASM file path as its sole command-line argument and writes the optimized circuit (valid OpenQASM 2.0) to stdout.

Target maximum CX gate counts per circuit are specified in `/app/targets.toml`. The optimized circuit must be unitarily equivalent to the original (global phase tolerance 1e-6).

Analysis tools are provided in `/app/tools/`:

- `python3 /app/tools/gate_stats.py <file.qasm>` — gate type and count breakdown
- `python3 /app/tools/qasm_sim.py <file.qasm>` — compute and display the circuit's full unitary matrix
- `python3 /app/tools/verify_equiv.py <original.qasm> <optimized.qasm>` — verify two circuits are unitarily equivalent

Do not use any quantum computing framework (Qiskit, Cirq, PyTKET, tket, pennylane, BQSKit, etc.). You may use numpy for linear algebra.

The optimizer must generalize beyond the provided circuits — it will also be tested on held-out circuits not present in `/app/circuits/`.
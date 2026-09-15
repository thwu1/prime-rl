`/app/` contains a quantum circuit simulation framework. The provided modules `/app/gates.py` (unitary matrix definitions and gate classification) and `/app/circuit.py` (`Circuit` class with Kronecker-product-based unitary computation) are complete. Benchmark circuits live in `/app/benchmarks/*.qasm` (OpenQASM 2.0 format), and `/app/Makefile` drives the pipeline via `make benchmark`.

Three skeleton files need working implementations:

**`/app/optimizer.py`** — `CircuitOptimizer.optimize(circuit) -> Circuit` must return a circuit with the same unitary (up to global phase) but fewer gates. Study the gate definitions in `/app/gates.py` and the benchmark circuits to determine what optimization strategies are needed. The optimizer must achieve meaningful reductions across all benchmarks, including circuits where redundant gates are not immediately adjacent.

**`/app/qasm_io.py`** — `parse_qasm(str) -> Circuit` and `write_qasm(Circuit) -> str` must correctly translate between OpenQASM 2.0 syntax and the internal `Circuit` representation. Refer to the benchmark `.qasm` files and `/app/gates.py` for the full set of gates that must be supported.

**`/app/run_pipeline.py`** — Process every `/app/benchmarks/*.qasm` file and write `/app/results/report.json`: a JSON array of objects with keys `file` (basename), `original_gates` (int), `optimized_gates` (int), `equivalent` (bool — unitary match up to global phase).

All benchmark circuits must report `equivalent: true` with strictly reduced gate counts.
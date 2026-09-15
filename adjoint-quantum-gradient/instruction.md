`/app/qcsim/` contains a quantum circuit simulation framework. Gate definitions (`/app/qcsim/gates.py`) and the circuit construction API (`/app/qcsim/circuit.py`) are complete. Three Python modules and one shell script are stubs that must be implemented:

**`/app/qcsim/engine.py`** — `apply_gate(state, matrix, targets)`, `apply_controlled_gate(state, matrix, controls, targets)`, and `simulate(circuit, params)`. See the docstrings in the stub for argument and return value specifications. A 16-qubit circuit with 240 gates must complete simulation in under 30 seconds.

**`/app/qcsim/differentiation.py`** — `expectation_value(state, obs_matrix, obs_qubits)` and `compute_gradient(circuit, params, obs_matrix, obs_qubits)`. Gradients must agree with central finite-difference approximations to within 1e-5.

**`/app/qcsim/qasm_parser.py`** — `parse_qasm(filepath)` reads an OpenQASM 2.0 file and returns a `Circuit` object. Must handle `qreg` declarations, standard gates (`h`, `x`, `y`, `z`, `cx`), and parameterized rotations (`rx`, `ry`, `rz`) with literal angle arguments. Sample circuits are at `/app/circuits/*.qasm`.

**`/app/pipeline.sh`** — Must produce two artifacts:

- `/app/results.db`: an SQLite database conforming to the schema in `/app/schema.sql`, populated with simulation results for every `.qasm` file in `/app/circuits/`. The `circuits` table gets one row per circuit; the `amplitudes` table gets one row per amplitude whose probability exceeds 0.001.
- `/app/report.json`: a JSON array sorted by circuit name. Each element has keys `name`, `n_qubits`, `n_gates`, and `states` (an array of `{"basis", "prob", "re", "im"}` objects ordered by basis state). The script must use `sqlite3` and `jq`.

State vectors use little-endian qubit ordering: index `i` encodes qubit `j` as bit `(i >> j) & 1`.
A database of quantum error correction codes at `/app/codes_db.json` was compiled from heterogeneous sources during a lab migration. Each entry specifies a code name, qubit count, Pauli stabilizer generators, and a two-qubit gate budget. Some entries were corrupted during the transfer — the nature and number of defects are unknown.

Audit every entry to determine whether it defines a valid stabilizer code. For each valid entry, synthesize a Stim-format state-preparation circuit whose output is a +1 eigenstate of all listed generators, using at most the specified number of two-qubit gates (Clifford gates only: H, S, S_DAG, CX, CZ, SWAP, X, Z, Y). For each invalid entry, provide a diagnosis explaining the specific defect.

Write results to `/app/output/results.json` as a JSON array. Each element must have keys: `"name"` (matching the code name), `"status"` (`"valid"` or `"invalid"`), `"diagnosis"` (empty string for valid entries, description of the defect for invalid), and `"circuit"` (Stim circuit string for valid entries, empty string for invalid).

Verification tools are at `/app/tools/`:
- `check_stabilizers.py` — `check_stabilizers(circuit_str, stabilizer_list)` returns a dict mapping each stabilizer to a boolean indicating +1 eigenstate preservation.
- `circuit_metric.py` — `compute_metrics(circuit_str)` returns a `CircuitMetrics` object with field `two_qubit_gates`.

The `stim` Python library (v1.15.0) is pre-installed.
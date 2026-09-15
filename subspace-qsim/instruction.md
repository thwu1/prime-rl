A 10-qubit quantum circuit is defined across multiple data formats at `/app/`:

- **SQLite database** `/app/circuit.db` — circuit structure in six normalized relational tables. Explore interactively with `sqlite3 /app/circuit.db` (use `.schema`, `.dump`, and SQL queries to understand the data model).
- **Binary parameter file** `/app/params.bin` — gate rotation angles stored as raw little-endian IEEE 754 64-bit doubles. The `gate_params` table in SQLite stores `bin_offset` (byte offset into this file) rather than the parameter value directly. Use `xxd` or `od` to inspect.
- **TOML configuration** `/app/observables.toml` — Hamiltonian observable terms in TOML array-of-tables format (`[[observables]]` / `[[observables.terms]]`).

Simulate the circuit starting from |0⟩^⊗10 and write `/app/results.json`:

```json
{
  "amplitudes": {"0": [re, im], "1": [re, im], ..., "1023": [re, im]},
  "expectation_values": [val1, val2, ...],
  "total_energy": float,
  "entanglement_entropy": float,
  "state_hash": "<sha256hex>"
}
```

- **amplitudes**: all 1024 complex amplitudes as `[real, imag]` pairs keyed by decimal basis-state index string
- **expectation_values**: for each observable in order, `coefficient × ⟨ψ|P|ψ⟩` where P is the Pauli-string operator
- **total_energy**: sum of all expectation values
- **entanglement_entropy**: Von Neumann entropy S = −Tr(ρ_A ln ρ_A) for bipartition {0,1,2,3,4} | {5,6,7,8,9}
- **state_hash**: SHA-256 hex digest of the state vector serialized as 1024 consecutive (real, imag) pairs of little-endian 64-bit doubles (index 0 through 1023 in order)

## Database Schema

- `circuit_meta(num_qubits)` — single row with qubit count
- `gates(gate_id PK, gate_order, gate_type, custom_matrix_id)` — one row per gate; execute in `gate_order` sequence; `gate_type` is one of H, X, Y, Z, S, T, Rx, Ry, Rz, or CUSTOM
- `gate_targets(gate_id, qubit, target_order)` — target qubit(s) for each gate, ordered by `target_order`
- `gate_params(gate_id, param_order, bin_offset)` — `bin_offset` is the byte position in `/app/params.bin` where the IEEE 754 double-precision parameter value is stored
- `gate_controls(gate_id, control_qubit, control_value)` — control conditions; `control_value=1` fires when qubit is |1⟩, `control_value=0` fires when qubit is |0⟩
- `custom_matrices(matrix_id, row_idx, col_idx, real_part, imag_part)` — element-wise storage of complex unitary matrices for CUSTOM gates; reconstruct via `custom_matrix_id` foreign key

## Conventions

- Qubit indices are 0-based. State-vector index uses little-endian bit ordering (qubit j = bit j).
- Multi-qubit gate matrices: least significant matrix index bit maps to smallest-numbered target qubit.
- Standard gates: H = (1/√2)[[1,1],[1,−1]], X = [[0,1],[1,0]], Y = [[0,−i],[i,0]], Z = [[1,0],[0,−1]], S = [[1,0],[0,i]], T = [[1,0],[0,e^(iπ/4)]], Rx(θ) = [[cos(θ/2),−i·sin(θ/2)],[−i·sin(θ/2),cos(θ/2)]], Ry(θ) = [[cos(θ/2),−sin(θ/2)],[sin(θ/2),cos(θ/2)]], Rz(θ) = [[e^(−iθ/2),0],[0,e^(iθ/2)]].
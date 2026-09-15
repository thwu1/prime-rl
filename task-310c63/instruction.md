`/app/network.json` defines a quantum network with five edges. Each edge carries noisy Bell pairs characterized by bit-flip probability `pX`, phase-flip probability `pZ`, a fidelity `threshold`, and a `max_pairs` budget. The single-pair state is Bell-diagonal:

    rho = (1-pX)(1-pZ)|Phi+><Phi+| + pX(1-pZ)|Psi+><Psi+| + (1-pX)pZ|Phi-><Phi-| + pX*pZ|Psi-><Psi-|

For N pairs on 2N qubits, pair k occupies qubit k (Alice, range 0..N-1) and qubit 2N-1-k (Bob, range N..2N-1). The output pair is always qubits N-1 and N. Fidelity is measured against |Phi+>. All circuits must obey LOCC: two-qubit gates may only couple qubits belonging to the same party.

Produce all of the following:

- `/app/simulator.py` — Python module exporting:
  - `initialize_pairs(n, px, pz)`: density matrix (2^2N x 2^2N complex array) for N noisy pairs
  - `compute_fidelity(rho, qubit_a, qubit_b, n_qubits)`: fidelity of the reduced two-qubit subsystem with |Phi+>
  - `check_locc(gates, n)`: returns `(bool, str)` where `gates` is a list of `(gate_name, [qubit_indices])` tuples

- `/app/circuits/` — One OpenQASM 3.0 file per edge (`E1.qasm` through `E5.qasm`). Each must begin with `OPENQASM 3.0;`, declare `qubit[2N]`, include measurements, and use only LOCC-compliant gates. Qubit count must equal twice the pairs consumed.

- `/app/results.db` — SQLite database with table `results` (columns: `edge_id` TEXT PRIMARY KEY, `fidelity` REAL, `success_probability` REAL, `num_pairs` INTEGER, `exceeds_threshold` INTEGER).

- `/app/results.json` — JSON keyed by edge ID with fields: `fidelity` (float), `success_probability` (float), `num_pairs` (int), `exceeds_threshold` (bool).

All post-distillation fidelities must strictly exceed each edge's threshold using at most `max_pairs` pairs. SQLite and JSON results must be consistent.
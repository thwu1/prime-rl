OpenQASM 2.0 circuits at `/app/circuits/*.qasm` use standard `qelib1.inc` gates (`h`, `x`, `y`, `z`, `s`, `sdg`, `t`, `tdg`, `cx`, `cz`, `swap`, `ccx`). No `qelib1.inc` file is provided; gate semantics follow the OpenQASM 2.0 specification.

Analyze every circuit (initial state |0...0>) and produce two artifacts:

**`/app/analysis.db`** — SQLite database with table `circuit_analysis`:

| Column | Type |
|--------|------|
| `circuit_name` | TEXT PRIMARY KEY — filename without `.qasm` |
| `num_qubits` | INTEGER |
| `probabilities` | TEXT — JSON `{"binary_label": probability}`, states with P > 1e-10 only |
| `equiv_probabilities` | TEXT — JSON, same format, for a functionally equivalent circuit restricted to {H, X, CNOT, T, Tdg, S, Sdg} |
| `naive_t_count` | INTEGER — total T + Tdg gates in the restricted circuit |
| `optimized_t_count` | INTEGER — T + Tdg after phase-gate merging on the restricted circuit |
| `bipartite_entropy` | REAL — entanglement entropy (log base 2) for cut A = {0..floor(n/2)-1}, B = remaining qubits |
| `max_bipartite_entropy` | REAL — maximum entanglement entropy over all non-trivial bipartitions |
| `meyer_wallach_measure` | REAL — global entanglement measure |
| `entanglement_class` | TEXT — multipartite entanglement classification |
| `magic_fraction` | REAL — non-stabilizerness measure |

**`/app/results.json`** — JSON mapping each circuit name to `probabilities`, `decomposed_probabilities`, `naive_t_count`, `optimized_t_count`, `bipartite_entropy`, `max_bipartite_entropy`, `meyer_wallach_measure`, `entanglement_class`, `magic_fraction`, corresponding to the DB columns above. Binary labels use MSB-first convention (leftmost character = qubit 0). Include only basis states with P > 1e-10.

**Phase-gate merging** (for `optimized_t_count`): After decomposing to the restricted gate set, build per-qubit gate timelines. When consecutive gates on a qubit are all single-qubit diagonal ({T, Tdg, S, Sdg}), merge them by summing phases (T=pi/4, Tdg=-pi/4, S=pi/2, Sdg=-pi/2). Re-express the merged phase k*pi/4 (mod 2pi) with minimal T+Tdg count: 0 if k is even, 1 if k is odd. "Consecutive on a qubit" means no gate of any arity acts on that qubit between them; gates on other qubits may interleave freely.

**Entanglement class**: Compute entanglement entropy for every non-trivial bipartition (every split into two non-empty subsets). Classify: `product` if entropy < 1e-10 for all bipartitions; `genuine` if entropy > 1e-10 for all bipartitions; `biseparable` otherwise. A bipartition splits qubits into sets A and B; entropy is the von Neumann entropy of the reduced density matrix Tr_B(|psi><psi|) using log base 2.

**Meyer-Wallach measure**: Q = 2(1 - (1/n) * sum_{k=0}^{n-1} Tr(rho_k^2)) where rho_k is the single-qubit reduced density matrix of qubit k. Q=0 for product states, Q=1 for maximally entangled states like GHZ.

**Magic fraction**: mu = 1 - Xi/2^n where Xi = sum over all P in {I,X,Y,Z}^{tensor n} of <psi|P|psi>^4. Equals 0 for stabilizer states (GHZ, Bell, computational basis); strictly positive for states requiring T gates.

Constraint: no external quantum computing packages (qiskit, cirq, pennylane, projectq, pyquil).
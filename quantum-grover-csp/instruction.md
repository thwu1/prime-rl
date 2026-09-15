`/app/problem.json` defines a constraint satisfaction problem over 6 binary variables with two kinds of constraints:

- **Parity constraints**: linear equations over GF(2) -- each specifies that the XOR of a subset of variables must equal a target value (0 or 1).
- **Hamming weight constraint**: the total number of 1-bits in the solution must equal a specified integer.

Implement a quantum solver using Qiskit and Grover's algorithm that finds all binary strings satisfying every constraint simultaneously.

Create `/app/quantum_solver.py` with at minimum:

- `build_marking_oracle(n, parity_constraints, target_weight)` returning a `QuantumCircuit` that implements a marking oracle for the combined constraints. Qubit convention: indices `0` through `n-1` are data qubits, the final qubit is the target qubit, and any intermediate qubits are ancillas that must be returned to the |0> state after the oracle acts.

- `solve(problem_path)` which reads the problem JSON, constructs the oracle, executes Grover's search with an appropriate iteration count, and returns the list of all satisfying assignments.

Run the solver to produce `/app/solutions.json`: a sorted JSON array of binary strings where character at position `i` gives the value of variable `x_i`.
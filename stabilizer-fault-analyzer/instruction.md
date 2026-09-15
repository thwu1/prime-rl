Create `/app/ft_analyzer.py` that exports two functions for analyzing fault tolerance of quantum stabilizer circuits expressed in Stim format.

A stabilizer circuit on n qubits consists of Clifford gates (H, S, CX). Decompose the circuit into m individual gate operations (packed Stim instructions like `CX 0 1 2 3` count as two separate CX operations). A single-point fault at location (qubit i, boundary j, Pauli P in {X,Y,Z}) inserts a Pauli error between the j-th and (j+1)-th operations. The output error is determined by conjugating the fault Pauli through the suffix circuit (operations j+1 through m) in the Heisenberg picture. Since Clifford gates map Paulis to Paulis, the result is always a tensor product of single-qubit Paulis (global phase ignored). Fault boundaries range from j=0 (before all gates) to j=m (after last gate), giving n*(m+1)*3 total fault locations.

A circuit with code distance d corrects errors of weight up to t = floor((d-1)/2). Flag qubits are ancillae whose error state (X or Y component) signals dangerous faults. The fault-tolerance score is the fraction of single-point faults that are either:
- low-weight: the error restricted to data qubits has weight <= t, or
- flagged: at least one flag qubit has an X or Y component in the output error.

**Required API:**

`propagate_fault(circuit_str, fault_qubit, fault_layer, fault_pauli, n_qubits)` — Returns a string of per-qubit Pauli labels (e.g. `"XZI"`) representing the output error for a single-point fault.

`compute_ft_score(circuit_str, data_qubits, flag_qubits, distance)` — Returns a float in [0, 1] representing the fraction of safe faults.

Test circuits and metadata are provided in `/app/problem.json`. The `stim` Python package is available via pip.
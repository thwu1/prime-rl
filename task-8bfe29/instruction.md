The Low Autocorrelation Binary Sequences (LABS) problem seeks binary sequences s in {-1, +1}^N minimizing E(s) = sum of C_k^2, where C_k are aperiodic autocorrelation coefficients. This NP-hard problem connects to quantum computing through its Ising Hamiltonian formulation, which introduces multi-body interaction index sets and counterdiabatic driving parameters.

A research group left incomplete reference materials and validation data for a Python framework at `/app/data/`. The mathematical specification (`spec.json`), a SQLite validation database (`reference.db`), a known-optima table (`known_optima.csv`), and a README describe the intended framework.

Implement the framework as a Python package at `/app/labs/` with these modules:

- **`energy.py`** -- Autocorrelation coefficients C_k, energy E(s), merit factor F(s) = N^2/(2E), and O(N) incremental energy-change computation for single-bit flips (returning both delta_E and the updated autocorrelation vector).

- **`interactions.py`** -- Enumeration of 2-body (G2) and 4-body (G4) Hamiltonian interaction index sets from the Trotterized counterdiabatic unitary. The generation rules use nested loops with floor-division bounds over qubit positions. Also: topology overlap invariants between interaction groups.

- **`theta.py`** -- Counterdiabatic schedule parameter chain: Gamma1 (linear combination of |G2| and |G4|), Gamma2 (lambda-dependent expression involving topology overlaps and interaction counts), variational alpha = -Gamma1/Gamma2, and final theta = dt * alpha * lambda_dot where lambda(t) = sin^2(pi*t / 2T) is the annealing schedule.

- **`symmetry.py`** -- Three energy-preserving involutions (negation, reversal, alternating inversion) generating an 8-element symmetry group, plus canonical form as the lexicographically smallest equivalent sequence.

- **`solver.py`** -- Memetic Tabu Search (MTS) optimizer: population-based search combining uniform crossover, mutation, and tabu search with aspiration criterion. Must find known optimal energies for N in {5, 7, 11, 13} and achieve E <= 30 for N = 21.

Explore the reference materials in `/app/data/` to discover exact mathematical formulas, loop bounds, and validation data. Query `reference.db` with `sqlite3` for interaction counts, exact index sets, theta reference values, and energy examples. The test suite at `/tests/test_state.py` defines the full API contract.
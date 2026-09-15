`/app/qubitization.py` implements a dense-matrix qubitization-based quantum phase estimation (QPE) pipeline for computing ground state energies of quantum Hamiltonians defined in `/app/systems.json`. The pipeline constructs LCU decompositions, PREPARE/SELECT oracles, a qubitization walk operator, and extracts energies via simulated QPE.

The implementation contains bugs that cause it to produce incorrect energy estimates. Running `python3 /app/qubitization.py` generates `/app/results.json`, but the reported `qpe_ground_energy` values are wrong for all three systems.

Fix the pipeline so that `/app/results.json` contains correct values for all systems (`heisenberg_2`, `mixed_signs`, `heisenberg_3`). Each system's `qpe_ground_energy` must agree with its `ground_energy_exact` within 0.1. Known exact ground state energies: the 2-qubit isotropic Heisenberg model is -3/4, the 3-qubit open Heisenberg chain is -1.0.

Reference source code from the qpe-toolbox library is available in `/app/reference/`.
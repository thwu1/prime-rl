`/app/model_params.json` specifies a quantum lattice fermion model with its physical parameters and conventions. An unvalidated analysis pipeline exists at `/app/analysis.py`. Produce a correct `/app/results.json` containing all quantities below.

| Key | Type | Meaning |
|-----|------|---------|
| `n_qubits` | int | Qubit count for the spin-orbital register |
| `n_jw_terms` | int | Pauli term count under Jordan-Wigner encoding |
| `n_bk_terms` | int | Pauli term count under Bravyi-Kitaev encoding |
| `jw_max_weight` | int | Maximum Pauli weight (JW) |
| `bk_max_weight` | int | Maximum Pauli weight (BK) |
| `jw_one_norm` | float | L1 norm of Pauli coefficients (JW) |
| `bk_one_norm` | float | L1 norm of Pauli coefficients (BK) |
| `ground_state_energy` | float | Lowest eigenvalue in the fixed-particle-number sector |
| `first_excited_energy` | float | Second-lowest distinct eigenvalue in that sector |
| `spectral_gap` | float | Gap between ground and first excited state |
| `ground_state_degeneracy` | int | Number of states at the ground energy (tolerance 1e-8) |
| `n_z2_symmetries` | int | Number of independent Z2 symmetries of the qubit Hamiltonian |
| `sector_eigenvalues` | list[int] | Ground-state eigenvalue (±1) for each Z2 symmetry generator |
| `tapered_ground_state_energy` | float | Ground energy from the symmetry- and particle-number-reduced subspace |
| `reduced_hilbert_space_dim` | int | Dimension of that reduced subspace |
| `n_tapered_qubits` | int | Effective qubit count after symmetry reduction |
| `one_rdm_trace` | float | Trace of the one-particle reduced density matrix |
| `one_rdm_real` | float[][] | Real part of the 1-RDM (γ_{pq} = ⟨ψ₀|a†_p a_q|ψ₀⟩) |
| `one_rdm_imag` | float[][] | Imaginary part of the 1-RDM |

Correctness criteria: energies accurate to 1e-6; the 1-RDM must be Hermitian with eigenvalues in [0, 1] and trace equal to the electron count; the tapered ground-state energy must agree with the full-sector ground-state energy to 1e-6.
Using QuTiP, compute steady-state density matrices of a two-level system (spin-boson model) coupled to a bosonic bath, comparing a non-perturbative method (HEOM) against a weak-coupling Lindblad master equation. Characterize where the perturbative treatment breaks down as the system-bath coupling strength increases.

## System definition (hbar = k_B = 1)

- System Hamiltonian: H_sys = (epsilon/2) sigma_z + (Delta/2) sigma_x
- System-bath coupling operator: Q = sigma_z
- Bath spectral density (Drude-Lorentz): J(omega) = 2 lambda gamma omega / (omega^2 + gamma^2)
- epsilon = 0.5, Delta = 1.0, gamma = 0.5, T = 0.5
- HEOM truncation: Nk = 2 Matsubara terms, default hierarchy depth NC = 5

## Required outputs

For each coupling strength lambda in {0.025, 0.05, 0.1, 0.25, 0.5, 1.0}, compute both the HEOM and Lindblad steady-state density matrices. For lambda = 0.5, also compute the HEOM steady state for NC in {2, 3, 4, 5, 6, 7, 8} to demonstrate hierarchy convergence.

Write the following CSV files to `/app/results/` (no header rows):

- `populations.csv` — lambda, P11_heom, P11_lindblad where P11 = <0|rho_ss|0>
- `coherences.csv` — lambda, abs_rho01_heom, abs_rho01_lindblad where values are |<0|rho_ss|1>|
- `trace_distances.csv` — lambda, trace_distance where trace_distance = 0.5 * Tr|rho_heom - rho_lindblad|
- `convergence.csv` — NC, P11_heom (for lambda = 0.5)

All numerical values must have at least 6 significant figures.
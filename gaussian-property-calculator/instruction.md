A Gaussian 16 output file for a water molecule (PBE1PBE/6-31G(d,p), geometry optimization + frequency calculation, GD3BJ dispersion, Toluene SCRF solvent) is at `/app/data/water.log`.

Build `/app/compute_properties.py` that parses this log file and independently computes molecular properties from the extracted raw data. Write all results to `/app/results.json`.

Do not use cclib or any quantum chemistry parsing library. Only numpy and scipy may be used for numerical computation.

Required output fields in `/app/results.json`:

- `initial_nre_hartree` (float): Nuclear repulsion energy in Hartree for the initial (pre-optimization) geometry. Compute from atomic coordinates and nuclear charges using the Coulomb formula in atomic units (convert coordinates from Angstroms to Bohr).

- `mulliken_charges` (list of 3 floats): Mulliken partial charges [O, H, H]. Parse the "Full Mulliken population analysis" matrix Q (which represents the element-wise product P*S of density and overlap matrices). Determine which basis functions belong to which atom from the MO coefficient section headers. Compute charges as q_A = Z_A - sum_{i in A, j} Q[i,j].

- `total_electrons` (float): Sum of all elements of the parsed Mulliken population matrix Q. This equals Tr(PS) and should be ~10.0 for water.

- `overlap_trace` (float): Trace of the overlap matrix S, derived from the density matrix P and the Mulliken population matrix Q via S[i,i] = Q[i,i] / P[i,i] for each diagonal element. For normalized Gaussian basis functions, each S[i,i] = 1, so the trace should be ~25.0.

- `density_matrix_max_error` (float): Maximum absolute element-wise difference between the density matrix reconstructed from the occupied MO coefficients (P = 2 * C_occ * C_occ^T, using the first 5 columns of the printed MO coefficient matrix) and the density matrix parsed directly from the "Density Matrix:" section of the log.

- `final_principal_moments` (list of 3 floats): Principal moments of inertia [I_a, I_b, I_c] in amu*bohr^2 for the final optimized geometry (from the archive line), sorted smallest to largest. Requires center-of-mass calculation, inertia tensor construction, and eigendecomposition.

- `final_rotational_constants` (list of 3 floats): Rotational constants [A, B, C] in GHz for the final optimized geometry, sorted largest to smallest. Compute from principal moments using B = h/(8*pi^2*I).

- `zpve_hartree` (float): Zero-point vibrational energy in Hartree/particle, computed from the harmonic vibrational frequencies using ZPVE = 0.5 * sum(h * c * nu_i) with frequencies in cm^-1.

- `final_scf_energy_hartree` (float): Final SCF energy (HF=...) extracted from the Gaussian archive line at the end of the log file.
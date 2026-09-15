The directory `/app/` contains the source code for LULESH 2.0 (Livermore Unstructured Lagrangian Explicit Shock Hydrodynamics), a proxy application that simulates a Sedov blast wave on an unstructured hexahedral mesh. The code is configured for serial compilation (no MPI).

The code compiles and runs without crashing, but produces numerically incorrect results. Multiple defects were introduced across the codebase during a refactoring — they span different source files and computational phases of the simulation pipeline. The number and nature of these defects are not known in advance.

Reference output from a correct build is available at `/reference/output_s10_i100.txt` (mesh size 10, 100 iterations) and `/reference/output_s15_i50.txt` (mesh size 15, 50 iterations). Additional reference outputs at `/reference/convergence/` for mesh sizes 8, 12, 16, and 20 (50 iterations each).

Build with `make` in `/app/` and run as `./lulesh2.0 -s <size> -i <iterations>`.

**Deliverables:**

1. Fix all defects in the LULESH source code so that simulation output matches the provided reference values exactly (within floating-point tolerance).

2. Design and implement a Grid Convergence Index (GCI) verification framework as `/app/gci_analysis.py`. This tool must run the corrected simulation at mesh sizes 8, 12, 16, and 20 (50 iterations each), then perform formal code verification following the Roache/Celik GCI procedure for non-uniform refinement ratios:
   - Compute observed convergence orders using the generalized Richardson extrapolation with iterative apparent-order estimation (handle both monotonic and oscillatory convergence)
   - Calculate GCI uncertainty bands for each successive grid pair using a safety factor of 1.25
   - Evaluate whether the solution is in the asymptotic convergence regime by comparing Richardson-extrapolated values from two overlapping grid triplets (sizes 20/16/12 and 16/12/8)
   - Determine whether the implementation achieves at least first-order spatial accuracy
   - Write a JSON report to `/app/gci_report.json` with these fields: `mesh_sizes` (list of ints), `energies` (dict mapping string mesh size to Final Origin Energy float), `convergence_order` (float — average apparent order from both triplets), `gci_fine` (float — GCI for finest grid pair), `gci_coarse` (float — GCI for coarser pair), `asymptotic_ratio` (float — ratio of Richardson extrapolations from the two triplets), `richardson_estimate` (float — extrapolated exact energy from finest triplet), and `assessment` (string — `"verified"` if convergence order ≥ 0.8 and asymptotic ratio is within [0.9, 1.1], otherwise `"not_verified"`)
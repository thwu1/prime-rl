Complete the four stub functions in `/app/sp2_solver.py`. A molecular simulation framework generates sparse symmetric Hamiltonian matrices for a multi-chain tight-binding system (`/app/hamiltonian.py`, `/app/config.json` — 400 atoms, 100 occupied states). A dense reference implementation is at `/app/baseline_dense.py`.

## Function specifications

### `gershgorin_bounds(H) -> (emin, emax)`

Compute eigenvalue bounds for sparse symmetric matrix `H` using Gershgorin circle theorem. Returns a tuple of floats `(emin, emax)` that are guaranteed lower and upper bounds on all eigenvalues of `H`. The bounds must contain every eigenvalue and must match the dense reference `gershgorin_bounds_dense` to within 1e-10.

### `sparse_sp2(H, n_occ, tol, trunc_thresh) -> (D, n_iter, idem_err)`

Compute the electronic density matrix `D` (the projector onto the `n_occ` lowest-energy eigenstates) from Hamiltonian `H` using iterative sparse purification. Returns a 3-tuple:
- `D`: `scipy.sparse.csr_matrix` — the density matrix
- `n_iter`: `int` — number of iterations to convergence
- `idem_err`: `float` — final idempotency error `||D^2 - D||_F`

The result must satisfy all of the following:
- **Idempotency**: `||D^2 - D||_F < 1e-8`
- **Trace**: `|trace(D) - n_occ| < 0.05`
- **Symmetry**: `||D - D^T||_F < 1e-10`
- **Convergence**: `n_iter < 100` and `idem_err < tol`
- **Spectral**: all eigenvalues of `D` must be within `1e-4` of either 0 or 1
- **Dense agreement**: on a 150-atom, 38-occupied-state system (seed=99, n_chains=3, chain_coupling=0.15), the Frobenius norm of `D_sparse - D_dense` must be less than 1.0 when compared against the dense reference `dense_sp2`

### `compute_comm_volume(H, partition) -> int`

Compute total communication volume for block-row distributed sparse matrix-matrix multiplication. Rows are assigned to contiguous blocks defined by `partition` (a strictly increasing list `[0, p1, ..., n]` with `len = n_blocks + 1`). For each block, count the number of unique column indices in that block's rows that fall outside the block's row range — this is the block's communication volume. Return the sum across all blocks as an integer.

Required behavior:
- A single-block partition `[0, n]` must return 0
- A diagonal matrix must return 0 for any partition
- The volume must be non-negative and monotonically non-decreasing as the number of blocks increases

### `optimal_partition(H, n_blocks) -> list[int]`

Find a row partition of `H` into `n_blocks` contiguous blocks that minimizes total communication volume (as defined by `compute_comm_volume`) subject to load balance constraints.

The returned partition must satisfy:
- Length exactly `n_blocks + 1`
- `partition[0] == 0` and `partition[-1] == H.shape[0]`
- Strictly monotonically increasing
- **Load balance**: for every block `k`, the number of nonzeros in `H[partition[k]:partition[k+1], :]` must not exceed `1.5 * H.nnz / n_blocks`
- **Quality**: the communication volume of the returned partition must be less than or equal to the communication volume of a uniform partition `[i * n // n_blocks for i in range(n_blocks)] + [n]`
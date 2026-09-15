A sequential 2D Jacobi iteration solver for the discrete Laplace equation is provided at `/app/jacobi_seq.c`. It operates on an `(N+2)x(N+2)` grid (default `N=60`) with fixed boundary conditions (top row = 100.0, all other boundaries = 0.0), runs 1000 iterations, and outputs the checksum (sum) and maximum value of the `NxN` interior grid points.

Create `/app/jacobi_rma.c` -- an MPI-parallel version that produces numerically equivalent results. A Makefile target `jacobi_rma` is provided at `/app/Makefile`.

**Requirements:**

- Decompose the `NxN` interior grid onto a 2D process grid (`Px x Py` where `Px*Py = nprocs`), automatically determining `Px` and `Py` from `nprocs` such that `N` is divisible by both. Must produce correct results for `nprocs` in {4, 6}.
- All inter-process data exchange (halo/ghost cell updates) must use MPI one-sided (RMA) communication exclusively. Do not use `MPI_Send`, `MPI_Recv`, `MPI_Sendrecv`, or any variant for data transfer.
- Use **passive target** synchronization: `MPI_Win_lock_all`/`MPI_Win_unlock_all` with `MPI_Win_flush` or `MPI_Win_flush_all`.
- Use MPI derived datatypes (`MPI_Type_vector` or `MPI_Type_create_subarray`) for the non-contiguous column halo exchanges in row-major storage.
- The grid size `N` must be overridable at compile time via `-DN=<value>` (use `#ifndef N` guard).
- Output exactly two lines on rank 0: `CHECKSUM: <value>` and `MAXVAL: <value>` using `%.10f` format, matching the sequential reference within floating-point tolerance.
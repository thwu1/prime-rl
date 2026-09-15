Implement a Partitioned Global Address Space (PGAS) distributed array library in C using MPI-3 RMA one-sided communication, then verify it by running the provided 2D Laplace equation solver.

## Context

`/app/pgas_array.h` defines the API for a distributed 2D array library inspired by the Global Arrays (GA) toolkit. `/app/main.c` is a complete Jacobi iterative solver for the 2D Laplace equation that calls this API. A `Makefile` is provided.

The solver distributes a 34x34 grid across 4 MPI processes in a 2D block decomposition. Each Jacobi iteration exchanges ghost (halo) cells between neighbours via the library, computes a 5-point stencil, and checks global convergence. On completion it writes 9 interior-point solution values to `/app/output.txt`.

## Task

Create `/app/pgas_array.c` — the full implementation of every function declared in `/app/pgas_array.h`. Key requirements:

- Distribute the global array in a 2D block decomposition across the process grid.
- Allocate local buffers that include ghost cells on all four sides.
- Use `MPI_Win` and `MPI_Get` or `MPI_Put` (with `MPI_Win_fence` or lock/unlock synchronisation) for the ghost cell exchange in `pgas_update_ghosts`.
- Handle boundary processes correctly (no neighbour on one or more sides).

After implementing the library, build and run:

```
cd /app && make && mpirun --allow-run-as-root -n 4 ./laplace_solver
```

The program must converge and produce `/app/output.txt` whose values match the analytical solution u(x,y) = 100 sin(pi x) sinh(pi y) / sinh(pi) within tolerance 0.5.
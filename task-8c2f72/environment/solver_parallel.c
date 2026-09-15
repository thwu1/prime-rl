/*
 * solver_parallel.c — Distributed 2D Poisson solver (to implement)
 *
 * Problem: −∇²u = f on [0,1]² with u=0 on the boundary
 *          f(x,y) = 2π²sin(πx)sin(πy)
 *          Exact:  u(x,y) = sin(πx)sin(πy)
 *
 * Study solver_serial.c for the complete serial algorithm and all
 * numerical parameters.  Implement a distributed-memory parallel
 * version that satisfies these constraints:
 *
 * Communication — MPI one-sided (RMA) only:
 *   - Create an RMA window (MPI_Win_create or MPI_Win_allocate)
 *   - Exchange ghost cells with MPI_Get (or MPI_Put)
 *   - Synchronize with MPI_Win_fence
 *   - Do NOT use MPI_Send / MPI_Recv / MPI_Isend / MPI_Irecv
 *
 * Topology — 2D Cartesian (MPI_Cart_create), must work with 4 processes
 *
 * Output — /app/results.json with this exact schema:
 * {
 *   "grid_size": <N>,
 *   "iterations": <iteration_count>,
 *   "residual": <final_max_change>,
 *   "method": "rma_fence",
 *   "points": [
 *     {"i": 8,  "j": 8,  "computed": <val>, "exact": <analytical>},
 *     {"i": 16, "j": 16, "computed": <val>, "exact": <analytical>},
 *     {"i": 24, "j": 24, "computed": <val>, "exact": <analytical>},
 *     {"i": 8,  "j": 24, "computed": <val>, "exact": <analytical>},
 *     {"i": 24, "j": 8,  "computed": <val>, "exact": <analytical>}
 *   ]
 * }
 *
 * Query-point indices (i,j) are 1-based interior grid indices.
 * The "exact" field = sin(π·i·h)·sin(π·j·h).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpi.h>

#define GRID_N    32
#define MAX_ITER  10000
#define TOL       1e-6

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);

    int rank, nprocs;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

    /* TODO: design and implement the distributed Poisson solver.
     * Refer to solver_serial.c for the numerical formulation. */

    if (rank == 0) {
        fprintf(stderr, "solver_parallel.c: not yet implemented\n");
    }

    MPI_Finalize();
    return 1;
}

/*
 * Parallel 2D Jacobi iteration using MPI RMA passive target synchronization
 * with derived datatypes for non-contiguous column halo exchange.
 *
 * Solves the discrete Laplace equation on an (N+2)x(N+2) grid.
 * Boundary conditions: top row = 100.0, all others = 0.0.
 * Runs NITER Jacobi iterations, outputs checksum and max of interior.
 *
 * Usage: mpiexec -n <nprocs> ./jacobi_rma
 */

#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef N
#define N 60
#endif
#define NITER 1000

/*
 * Factor nprocs into px * py such that:
 *   px * py == nprocs, N % px == 0, N % py == 0,
 *   and |px - py| is minimised (closest to square).
 * Returns 0 on success, -1 if no valid factoring exists.
 */
static int factor_procs(int nprocs, int grid_n, int *px, int *py)
{
    int best_diff = nprocs + 1;
    *px = 0;
    *py = 0;
    for (int p = 1; p * p <= nprocs; p++) {
        if (nprocs % p != 0)
            continue;
        int q = nprocs / p;
        if (grid_n % p == 0 && grid_n % q == 0) {
            int diff = q - p;
            if (diff < best_diff) {
                best_diff = diff;
                *px = p;
                *py = q;
            }
        }
    }
    return (*px == 0) ? -1 : 0;
}

int main(int argc, char **argv)
{
    int rank, nprocs;
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

    int px, py;
    if (factor_procs(nprocs, N, &px, &py) != 0) {
        if (rank == 0)
            fprintf(stderr, "Cannot decompose %d procs for grid N=%d\n", nprocs, N);
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    int lr = N / px;           /* local interior rows  */
    int lc = N / py;           /* local interior cols  */
    int my_pr = rank / py;     /* row in process grid  */
    int my_pc = rank % py;     /* col in process grid  */

    /* Neighbor ranks (-1 = physical boundary, no neighbor) */
    int nbr_up    = (my_pr > 0)      ? (my_pr - 1) * py + my_pc : -1;
    int nbr_down  = (my_pr < px - 1) ? (my_pr + 1) * py + my_pc : -1;
    int nbr_left  = (my_pc > 0)      ? my_pr * py + (my_pc - 1) : -1;
    int nbr_right = (my_pc < py - 1) ? my_pr * py + (my_pc + 1) : -1;

    /* Local storage: (lr+2) x (lc+2) with ghost/boundary cells */
    int stride     = lc + 2;
    int local_size = (lr + 2) * stride;
    double *u     = (double *)calloc(local_size, sizeof(double));
    double *u_new = (double *)calloc(local_size, sizeof(double));

    if (!u || !u_new) {
        fprintf(stderr, "Rank %d: allocation failed\n", rank);
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    /* 2D indexing macro: G(grid, row, col) */
    #define G(grid, i, j) ((grid)[(i) * stride + (j)])

    /* Boundary: top-edge processes have physical top boundary = 100.0 */
    if (my_pr == 0) {
        for (int j = 0; j < stride; j++) {
            G(u, 0, j) = 100.0;
            G(u_new, 0, j) = 100.0;
        }
    }
    /* Bottom / left / right physical boundaries = 0.0 (already from calloc) */

    /* ------ RMA setup ------ */

    /* Create window exposing u for remote one-sided access */
    MPI_Win win;
    MPI_Win_create(u, (MPI_Aint)local_size * (MPI_Aint)sizeof(double),
                   (int)sizeof(double),       /* displacement unit */
                   MPI_INFO_NULL, MPI_COMM_WORLD, &win);

    /* Derived datatype for a column vector: lr elements, stride 'stride' */
    MPI_Datatype col_type;
    MPI_Type_vector(lr, 1, stride, MPI_DOUBLE, &col_type);
    MPI_Type_commit(&col_type);

    /* ------ Iteration loop under passive-target epoch ------ */

    MPI_Win_lock_all(0, win);

    for (int iter = 0; iter < NITER; iter++) {

        /* --- Push halo data to neighbours --- */

        /* Top interior row -> neighbour above's bottom ghost row */
        if (nbr_up >= 0) {
            MPI_Put(&G(u, 1, 1), lc, MPI_DOUBLE,
                    nbr_up, (MPI_Aint)((lr + 1) * stride + 1),
                    lc, MPI_DOUBLE, win);
        }

        /* Bottom interior row -> neighbour below's top ghost row */
        if (nbr_down >= 0) {
            MPI_Put(&G(u, lr, 1), lc, MPI_DOUBLE,
                    nbr_down, (MPI_Aint)(0 * stride + 1),
                    lc, MPI_DOUBLE, win);
        }

        /* Left interior column -> neighbour left's right ghost column */
        if (nbr_left >= 0) {
            MPI_Put(&G(u, 1, 1), 1, col_type,
                    nbr_left, (MPI_Aint)(1 * stride + (lc + 1)),
                    1, col_type, win);
        }

        /* Right interior column -> neighbour right's left ghost column */
        if (nbr_right >= 0) {
            MPI_Put(&G(u, 1, lc), 1, col_type,
                    nbr_right, (MPI_Aint)(1 * stride + 0),
                    1, col_type, win);
        }

        /* Ensure all Puts are completed at their targets */
        MPI_Win_flush_all(win);
        /* Global barrier so every process has finished pushing */
        MPI_Barrier(MPI_COMM_WORLD);
        /* Synchronise public/private copies for local load access */
        MPI_Win_sync(win);

        /* --- Jacobi stencil update --- */
        for (int i = 1; i <= lr; i++)
            for (int j = 1; j <= lc; j++)
                G(u_new, i, j) = 0.25 * (G(u, i - 1, j) + G(u, i + 1, j) +
                                          G(u, i, j - 1) + G(u, i, j + 1));

        /* Copy updated interior back into window memory (preserves ghost/boundary) */
        for (int i = 1; i <= lr; i++)
            memcpy(&G(u, i, 1), &G(u_new, i, 1), lc * sizeof(double));

        /* Sync private copy (modified by memcpy) to public copy,
         * then barrier so all processes have unified copies before
         * the next iteration's MPI_Put operations modify public copies. */
        MPI_Win_sync(win);
        MPI_Barrier(MPI_COMM_WORLD);
    }

    MPI_Win_unlock_all(win);

    /* ------ Reduce results to rank 0 ------ */

    double local_sum = 0.0, local_max = 0.0;
    for (int i = 1; i <= lr; i++)
        for (int j = 1; j <= lc; j++) {
            local_sum += G(u, i, j);
            if (G(u, i, j) > local_max)
                local_max = G(u, i, j);
        }

    double global_sum, global_max;
    MPI_Reduce(&local_sum, &global_sum, 1, MPI_DOUBLE, MPI_SUM, 0, MPI_COMM_WORLD);
    MPI_Reduce(&local_max, &global_max, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);

    if (rank == 0) {
        printf("CHECKSUM: %.10f\n", global_sum);
        printf("MAXVAL: %.10f\n", global_max);
    }

    /* Cleanup */
    MPI_Type_free(&col_type);
    MPI_Win_free(&win);
    free(u);
    free(u_new);
    MPI_Finalize();
    return 0;
}

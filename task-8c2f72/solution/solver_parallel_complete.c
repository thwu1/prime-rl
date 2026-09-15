/*
 * solver_parallel_complete.c — Distributed 2D Poisson solver (complete)
 *
 * Solves −∇²u = f on [0,1]² with u = 0 on the boundary.
 * Source term: f(x,y) = 2π² sin(πx) sin(πy)
 * Exact solution: u(x,y) = sin(πx) sin(πy)
 *
 * Uses 2D Cartesian domain decomposition with MPI one-sided
 * communication (RMA) for inter-process ghost cell exchange.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mpi.h>

#define GRID_N    32
#define MAX_ITER  10000
#define TOL       1e-6
#define NQ        5

int main(int argc, char **argv)
{
    int world_rank, world_size;
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
    MPI_Comm_size(MPI_COMM_WORLD, &world_size);

    /* --- 2D Cartesian topology --- */
    int dims[2] = {0, 0};
    MPI_Dims_create(world_size, 2, dims);

    int periods[2] = {0, 0};
    MPI_Comm cart_comm;
    MPI_Cart_create(MPI_COMM_WORLD, 2, dims, periods, 1, &cart_comm);

    int cart_rank;
    MPI_Comm_rank(cart_comm, &cart_rank);
    int coords[2];
    MPI_Cart_coords(cart_comm, cart_rank, 2, coords);
    /* coords[0] = row position (y-direction)
       coords[1] = col position (x-direction) */

    /* --- Local grid dimensions --- */
    int local_ny = GRID_N / dims[0];   /* interior rows per process */
    int local_nx = GRID_N / dims[1];   /* interior cols per process */

    if (GRID_N % dims[0] != 0 || GRID_N % dims[1] != 0) {
        if (cart_rank == 0)
            fprintf(stderr, "Error: N=%d not divisible by process grid %dx%d\n",
                    GRID_N, dims[0], dims[1]);
        MPI_Finalize();
        return 1;
    }

    /* Global 0-based starting row/col of this process's interior block */
    int global_row_start = coords[0] * local_ny;
    int global_col_start = coords[1] * local_nx;

    /* Local array dimensions with ghost cells (width 1 each side) */
    int lnx = local_nx + 2;
    int lny = local_ny + 2;
    int local_size = lnx * lny;

    /* u is window memory; u_new is scratch for Jacobi update */
    double *u     = (double *)calloc(local_size, sizeof(double));
    double *u_new = (double *)calloc(local_size, sizeof(double));

    /* --- MPI window on u --- */
    MPI_Win win;
    MPI_Win_create(u, (MPI_Aint)(local_size * sizeof(double)),
                   (int)sizeof(double), MPI_INFO_NULL, cart_comm, &win);

    /* --- Neighbor ranks --- */
    int south, north, west, east;
    MPI_Cart_shift(cart_comm, 0, 1, &south, &north);
    /* south = coords[0]-1 neighbor,  north = coords[0]+1 neighbor */
    MPI_Cart_shift(cart_comm, 1, 1, &west, &east);
    /* west  = coords[1]-1 neighbor,  east  = coords[1]+1 neighbor */

    /* --- Right-hand side --- */
    double h  = 1.0 / (GRID_N + 1);
    double h2 = h * h;
    double pi = acos(-1.0);
    double *f = (double *)calloc(local_size, sizeof(double));

    for (int jj = 1; jj <= local_ny; jj++) {
        for (int ii = 1; ii <= local_nx; ii++) {
            int gi = global_col_start + ii;   /* 1-based global col (x) */
            int gj = global_row_start + jj;   /* 1-based global row (y) */
            double x = gi * h;
            double y = gj * h;
            f[jj * lnx + ii] = 2.0 * pi * pi * sin(pi * x) * sin(pi * y);
        }
    }

    /* =================================================================
     *  Jacobi iteration
     *
     *  Each iteration uses TWO fences:
     *    Fence A  –  completes MPI_Gets  (ghost cells become valid)
     *    Fence B  –  completes local writes (updated u visible to neighbors)
     *  Gets and local writes are in separate access epochs so they
     *  never conflict on the same window memory.
     * ================================================================= */

    double global_max_diff = 0.0;
    int    num_iters = 0;

    /* Open the first access epoch (for Gets) */
    MPI_Win_fence(MPI_MODE_NOPRECEDE, win);

    for (int iter = 0; iter < MAX_ITER; iter++) {
        num_iters++;

        /* ---- Epoch for Gets: read ghost cells from neighbors ---- */

        /* North ghost row  (my iy = local_ny+1)  <--  north neighbor's iy = 1 */
        if (north != MPI_PROC_NULL) {
            MPI_Get(&u[(local_ny + 1) * lnx + 1],
                    local_nx, MPI_DOUBLE,
                    north, 1 * lnx + 1,
                    local_nx, MPI_DOUBLE, win);
        }

        /* South ghost row  (my iy = 0)  <--  south neighbor's iy = local_ny */
        if (south != MPI_PROC_NULL) {
            MPI_Get(&u[0 * lnx + 1],
                    local_nx, MPI_DOUBLE,
                    south, local_ny * lnx + 1,
                    local_nx, MPI_DOUBLE, win);
        }

        /* East ghost column  (my ix = local_nx+1)  <--  east neighbor's ix = 1 */
        if (east != MPI_PROC_NULL) {
            for (int jj = 1; jj <= local_ny; jj++) {
                MPI_Get(&u[jj * lnx + (local_nx + 1)],
                        1, MPI_DOUBLE,
                        east, jj * lnx + 1,
                        1, MPI_DOUBLE, win);
            }
        }

        /* West ghost column  (my ix = 0)  <--  west neighbor's ix = local_nx */
        if (west != MPI_PROC_NULL) {
            for (int jj = 1; jj <= local_ny; jj++) {
                MPI_Get(&u[jj * lnx + 0],
                        1, MPI_DOUBLE,
                        west, jj * lnx + local_nx,
                        1, MPI_DOUBLE, win);
            }
        }

        /* Fence A: complete all Gets — ghost cells are now valid */
        MPI_Win_fence(0, win);

        /* ---- Epoch for local access: stencil computation ---- */

        double max_diff = 0.0;
        for (int jj = 1; jj <= local_ny; jj++) {
            for (int ii = 1; ii <= local_nx; ii++) {
                int idx = jj * lnx + ii;
                u_new[idx] = 0.25 * (
                    u[(jj - 1) * lnx + ii] +   /* south neighbor */
                    u[(jj + 1) * lnx + ii] +   /* north neighbor */
                    u[jj * lnx + (ii - 1)] +   /* west  neighbor */
                    u[jj * lnx + (ii + 1)] +   /* east  neighbor */
                    h2 * f[idx]
                );
                double diff = fabs(u_new[idx] - u[idx]);
                if (diff > max_diff) max_diff = diff;
            }
        }

        /* Copy interior of u_new into u (local write to window memory) */
        for (int jj = 1; jj <= local_ny; jj++) {
            memcpy(&u[jj * lnx + 1],
                   &u_new[jj * lnx + 1],
                   local_nx * sizeof(double));
        }

        /* Fence B: make local writes visible to other processes' Gets */
        MPI_Win_fence(0, win);

        /* Global convergence check */
        MPI_Allreduce(&max_diff, &global_max_diff, 1,
                      MPI_DOUBLE, MPI_MAX, cart_comm);
        if (global_max_diff < TOL) break;
    }

    /* Close the final RMA epoch */
    MPI_Win_fence(MPI_MODE_NOSUCCEED, win);

    /* =================================================================
     *  Gather solution at query points
     * ================================================================= */

    int qi[NQ] = {8, 16, 24,  8, 24};   /* 1-based column (x) */
    int qj[NQ] = {8, 16, 24, 24,  8};   /* 1-based row    (y) */
    double qvals[NQ];

    for (int q = 0; q < NQ; q++) {
        double local_val = 0.0;
        int li = qi[q] - global_col_start;   /* local col index (1-based) */
        int lj = qj[q] - global_row_start;   /* local row index (1-based) */
        if (li >= 1 && li <= local_nx && lj >= 1 && lj <= local_ny)
            local_val = u[lj * lnx + li];

        MPI_Allreduce(&local_val, &qvals[q], 1,
                      MPI_DOUBLE, MPI_SUM, cart_comm);
    }

    /* =================================================================
     *  Write results.json from rank 0
     * ================================================================= */

    if (cart_rank == 0) {
        FILE *fp = fopen("/app/results.json", "w");
        if (!fp) { perror("fopen"); MPI_Abort(cart_comm, 1); }

        fprintf(fp, "{\n");
        fprintf(fp, "  \"grid_size\": %d,\n", GRID_N);
        fprintf(fp, "  \"iterations\": %d,\n", num_iters);
        fprintf(fp, "  \"residual\": %.15e,\n", global_max_diff);
        fprintf(fp, "  \"method\": \"rma_fence\",\n");
        fprintf(fp, "  \"points\": [\n");
        for (int q = 0; q < NQ; q++) {
            double x = qi[q] * h;
            double y = qj[q] * h;
            double exact = sin(pi * x) * sin(pi * y);
            fprintf(fp,
                "    {\"i\": %d, \"j\": %d, \"computed\": %.15e, \"exact\": %.15e}%s\n",
                qi[q], qj[q], qvals[q], exact, (q < NQ - 1) ? "," : "");
        }
        fprintf(fp, "  ]\n");
        fprintf(fp, "}\n");
        fclose(fp);

        printf("Converged in %d iterations, residual = %.6e\n",
               num_iters, global_max_diff);
    }

    /* --- Cleanup --- */
    MPI_Win_free(&win);
    free(u);
    free(u_new);
    free(f);
    MPI_Comm_free(&cart_comm);
    MPI_Finalize();
    return 0;
}

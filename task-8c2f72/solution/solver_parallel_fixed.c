/*
 * solver_parallel.c — MPI-parallel 2D Poisson solver (corrected)
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
#define NQUERY    5

int main(int argc, char **argv)
{
    int rank, nprocs;
    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &nprocs);

    /* 2D Cartesian process topology */
    int pdims[2] = {0, 0};
    MPI_Dims_create(nprocs, 2, pdims);

    int periodic[2] = {0, 0};
    MPI_Comm cart;
    MPI_Cart_create(MPI_COMM_WORLD, 2, pdims, periodic, 1, &cart);

    int me;
    MPI_Comm_rank(cart, &me);
    int coords[2];
    MPI_Cart_coords(cart, me, 2, coords);

    /* Local subdomain sizes */
    int loc_ny = GRID_N / pdims[0];
    int loc_nx = GRID_N / pdims[1];

    if (GRID_N % pdims[0] || GRID_N % pdims[1]) {
        if (me == 0)
            fprintf(stderr, "GRID_N=%d not divisible by %dx%d topology\n",
                    GRID_N, pdims[0], pdims[1]);
        MPI_Finalize();
        return 1;
    }

    int row0 = coords[0] * loc_ny;
    int col0 = coords[1] * loc_nx;

    /* Local buffer: interior + width-1 ghost border */
    int sx = loc_nx + 2;
    int sy = loc_ny + 2;
    int buflen = sx * sy;

    double *u    = (double *)calloc(buflen, sizeof(double));
    double *unew = (double *)calloc(buflen, sizeof(double));

    /* RMA window over u */
    MPI_Win win;
    MPI_Win_create(u, (MPI_Aint)(buflen * sizeof(double)),
                   (int)sizeof(double), MPI_INFO_NULL, cart, &win);

    /* Neighbour ranks — FIX 1: correct source/dest ordering for dim 1 */
    int south, north, west, east;
    MPI_Cart_shift(cart, 0, 1, &south, &north);
    MPI_Cart_shift(cart, 1, 1, &west,  &east);

    /* Grid spacing — FIX 3: h = 1/(N+1) for N interior points on [0,1] */
    double h  = 1.0 / (GRID_N + 1);
    double h2 = h * h;
    double pi = acos(-1.0);
    double *f = (double *)calloc(buflen, sizeof(double));

    for (int j = 1; j <= loc_ny; j++) {
        for (int i = 1; i <= loc_nx; i++) {
            int gi = col0 + i;
            int gj = row0 + j;
            double x = gi * h;
            double y = gj * h;
            f[j * sx + i] = 2.0 * pi * pi * sin(pi * x) * sin(pi * y);
        }
    }

    /* Iterative solve */
    double gmax = 0.0;
    int iters = 0;

    MPI_Win_fence(MPI_MODE_NOPRECEDE, win);

    for (int it = 0; it < MAX_ITER; it++) {
        iters++;

        /* Fetch ghost borders from neighbours */

        /* FIX 2: fetch first interior row (row 1) from north, not last (row loc_ny) */
        if (north != MPI_PROC_NULL)
            MPI_Get(&u[(loc_ny + 1) * sx + 1], loc_nx, MPI_DOUBLE,
                    north, 1 * sx + 1, loc_nx, MPI_DOUBLE, win);

        if (south != MPI_PROC_NULL)
            MPI_Get(&u[1], loc_nx, MPI_DOUBLE,
                    south, loc_ny * sx + 1, loc_nx, MPI_DOUBLE, win);

        if (east != MPI_PROC_NULL)
            for (int j = 1; j <= loc_ny; j++)
                MPI_Get(&u[j * sx + loc_nx + 1], 1, MPI_DOUBLE,
                        east, j * sx + 1, 1, MPI_DOUBLE, win);

        if (west != MPI_PROC_NULL)
            for (int j = 1; j <= loc_ny; j++)
                MPI_Get(&u[j * sx], 1, MPI_DOUBLE,
                        west, j * sx + loc_nx, 1, MPI_DOUBLE, win);

        MPI_Win_fence(0, win);

        /* 5-point stencil update */
        double dmax = 0.0;
        for (int j = 1; j <= loc_ny; j++) {
            for (int i = 1; i <= loc_nx; i++) {
                int c = j * sx + i;
                unew[c] = 0.25 * (u[(j-1)*sx+i] + u[(j+1)*sx+i]
                                + u[j*sx+(i-1)] + u[j*sx+(i+1)]
                                + h2 * f[c]);
                double d = fabs(unew[c] - u[c]);
                if (d > dmax) dmax = d;
            }
        }

        for (int j = 1; j <= loc_ny; j++)
            memcpy(&u[j * sx + 1], &unew[j * sx + 1],
                   loc_nx * sizeof(double));

        MPI_Win_fence(0, win);

        MPI_Allreduce(&dmax, &gmax, 1, MPI_DOUBLE, MPI_MAX, cart);
        if (gmax < TOL) break;
    }

    MPI_Win_fence(MPI_MODE_NOSUCCEED, win);

    /* Collect query-point values */
    int qi[NQUERY] = { 8, 16, 24,  8, 24};
    int qj[NQUERY] = { 8, 16, 24, 24,  8};
    double qv[NQUERY];

    for (int q = 0; q < NQUERY; q++) {
        double val = 0.0;
        int li = qi[q] - col0;
        int lj = qj[q] - row0;
        if (li >= 1 && li <= loc_nx && lj >= 1 && lj <= loc_ny)
            val = u[lj * sx + li];
        MPI_Allreduce(&val, &qv[q], 1, MPI_DOUBLE, MPI_SUM, cart);
    }

    /* Write results */
    if (me == 0) {
        FILE *fp = fopen("/app/results.json", "w");
        if (!fp) { perror("fopen"); MPI_Abort(cart, 1); }
        fprintf(fp, "{\n  \"grid_size\": %d,\n  \"iterations\": %d,\n"
                    "  \"residual\": %.15e,\n  \"points\": [\n",
                GRID_N, iters, gmax);
        for (int q = 0; q < NQUERY; q++) {
            double xq = qi[q] * h, yq = qj[q] * h;
            double ex = sin(pi * xq) * sin(pi * yq);
            fprintf(fp, "    {\"i\": %d, \"j\": %d, \"computed\": %.15e, "
                        "\"exact\": %.15e}%s\n",
                    qi[q], qj[q], qv[q], ex, q < NQUERY-1 ? "," : "");
        }
        fprintf(fp, "  ]\n}\n");
        fclose(fp);
        printf("Parallel: %d iters, residual %.6e\n", iters, gmax);
    }

    MPI_Win_free(&win);
    free(u); free(unew); free(f);
    MPI_Comm_free(&cart);
    MPI_Finalize();
    return 0;
}

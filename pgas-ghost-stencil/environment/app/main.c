/* main.c — 2D Laplace equation solver using Jacobi iteration
 *          with a PGAS distributed array library.
 *
 * Solves  nabla^2 u = 0  on [0,1] x [0,1]  with Dirichlet BCs:
 *
 *     u(x, 0) = 0                         (bottom)
 *     u(x, 1) = 100 * sin(pi * x)         (top)
 *     u(0, y) = 0                         (left)
 *     u(1, y) = 0                         (right)
 *
 * Grid: N x N points (including boundary), spacing h = 1/(N-1).
 * Point (i,j)  maps to  (x,y) = (j*h, i*h).
 *
 * Must be run with exactly 4 MPI processes:
 *     mpirun -n 4 ./laplace_solver
 *
 * Writes verification-point values to /app/output.txt.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include "pgas_array.h"

#define N         34      /* grid size including boundary points      */
#define GW        1       /* ghost-cell width                         */
#define MAX_ITER  8000    /* maximum Jacobi iterations                */
#define TOL       1e-4    /* convergence tolerance (max-norm)         */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Nine interior verification points */
static const int vpts[][2] = {
    { 8,  8}, { 8, 17}, { 8, 25},
    {17,  8}, {17, 17}, {17, 25},
    {25,  8}, {25, 17}, {25, 25}
};
#define NVP 9

int main(int argc, char **argv)
{
    int    me, np, lo[2], hi[2], ld_u, ld_n, iter;
    double *u, *un, h = 1.0 / (N - 1), gdiff;

    pgas_init(&argc, &argv);
    me = pgas_myproc();
    np = pgas_nprocs();

    if (np != 4) {
        if (me == 0)
            fprintf(stderr, "Error: this program requires exactly 4 processes\n");
        pgas_finalize();
        return 1;
    }

    /* Create two distributed arrays: current (ga) and next (gn) */
    pgas_handle_t ga = pgas_create_2d(N, N, GW);
    pgas_handle_t gn = pgas_create_2d(N, N, GW);
    if (ga < 0 || gn < 0) {
        if (me == 0) fprintf(stderr, "Error: array creation failed\n");
        pgas_finalize();
        return 1;
    }

    pgas_fill(ga, 0.0);
    pgas_fill(gn, 0.0);
    pgas_sync();

    pgas_distribution(ga, me, lo, hi);
    pgas_access_local(ga, &u,  &ld_u);
    pgas_access_local(gn, &un, &ld_n);

    /* ---------- set boundary conditions ---------- */
    for (int li = 0; li <= hi[0] - lo[0]; li++) {
        for (int lj = 0; lj <= hi[1] - lo[1]; lj++) {
            int    gi = lo[0] + li, gj = lo[1] + lj;
            double v  = 0.0;
            int    bd = 0;

            if (gi == 0)     { v = 0.0;                              bd = 1; }
            if (gi == N - 1) { v = 100.0 * sin(M_PI * gj * h);      bd = 1; }
            if (gj == 0)     { v = 0.0;                              bd = 1; }
            if (gj == N - 1) { v = 0.0;                              bd = 1; }

            if (bd) {
                u [(li + GW) * ld_u + (lj + GW)] = v;
                un[(li + GW) * ld_n + (lj + GW)] = v;
            }
        }
    }
    pgas_sync();

    /* ---------- Jacobi iteration ---------- */
    for (iter = 0; iter < MAX_ITER; iter++) {

        pgas_update_ghosts(ga);

        double lmd = 0.0;                       /* local max diff */

        for (int li = 0; li <= hi[0] - lo[0]; li++) {
            for (int lj = 0; lj <= hi[1] - lo[1]; lj++) {
                int gi = lo[0] + li, gj = lo[1] + lj;

                /* boundary points: copy unchanged */
                if (gi == 0 || gi == N - 1 || gj == 0 || gj == N - 1) {
                    un[(li + GW) * ld_n + (lj + GW)] =
                        u[(li + GW) * ld_u + (lj + GW)];
                    continue;
                }

                int c = (li + GW) * ld_u + (lj + GW);
                double nv = 0.25 * (u[c - ld_u] + u[c + ld_u] +
                                    u[c - 1]    + u[c + 1]);
                double d  = fabs(nv - u[c]);
                if (d > lmd) lmd = d;
                un[(li + GW) * ld_n + (lj + GW)] = nv;
            }
        }

        /* swap: copy new -> old */
        for (int li = 0; li <= hi[0] - lo[0]; li++)
            for (int lj = 0; lj <= hi[1] - lo[1]; lj++) {
                int c  = (li + GW) * ld_u + (lj + GW);
                int cn = (li + GW) * ld_n + (lj + GW);
                u[c] = un[cn];
            }

        /* global convergence check */
        MPI_Allreduce(&lmd, &gdiff, 1, MPI_DOUBLE, MPI_MAX,
                      MPI_COMM_WORLD);
        if (gdiff < TOL) {
            if (me == 0)
                printf("Converged: %d iterations, max_diff = %e\n",
                       iter + 1, gdiff);
            break;
        }
    }

    if (iter == MAX_ITER && me == 0)
        printf("Not converged after %d iterations, max_diff = %e\n",
               MAX_ITER, gdiff);

    pgas_sync();

    /* ---------- collect verification-point values on rank 0 ---------- */
    double lv[NVP], gv[NVP];
    for (int k = 0; k < NVP; k++) {
        int gi = vpts[k][0], gj = vpts[k][1];
        lv[k] = 0.0;
        if (gi >= lo[0] && gi <= hi[0] && gj >= lo[1] && gj <= hi[1]) {
            int li = gi - lo[0], lj = gj - lo[1];
            lv[k] = u[(li + GW) * ld_u + (lj + GW)];
        }
    }
    MPI_Reduce(lv, gv, NVP, MPI_DOUBLE, MPI_SUM, 0, MPI_COMM_WORLD);

    /* ---------- write output ---------- */
    if (me == 0) {
        FILE *fp = fopen("/app/output.txt", "w");
        if (!fp) { perror("fopen"); pgas_finalize(); return 1; }
        fprintf(fp, "%d\n", (iter < MAX_ITER) ? iter + 1 : MAX_ITER);
        for (int k = 0; k < NVP; k++)
            fprintf(fp, "%d %d %.10f\n", vpts[k][0], vpts[k][1], gv[k]);
        fclose(fp);
        printf("Results written to /app/output.txt\n");
    }

    pgas_destroy(ga);
    pgas_destroy(gn);
    pgas_finalize();
    return 0;
}

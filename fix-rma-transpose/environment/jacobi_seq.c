/*
 * Sequential 2D Jacobi iteration for the discrete Laplace equation.
 *
 * Grid: (N+2) x (N+2) including fixed boundary cells.
 * Boundary conditions: top row = 100.0, all others = 0.0.
 * Interior initialized to 0.0.
 * Runs NITER Jacobi iterations, then outputs checksum and max of interior.
 */

#include <stdio.h>
#include <stdlib.h>

#ifndef N
#define N 60
#endif
#define NITER 1000

#define IDX(i, j) ((i) * (N + 2) + (j))

int main(void)
{
    double *u     = (double *)calloc((N + 2) * (N + 2), sizeof(double));
    double *u_new = (double *)calloc((N + 2) * (N + 2), sizeof(double));
    int i, j, iter;

    if (!u || !u_new) {
        fprintf(stderr, "Allocation failed\n");
        return 1;
    }

    /* Boundary: top row (row 0) = 100.0; others = 0.0 from calloc */
    for (j = 0; j < N + 2; j++) {
        u[IDX(0, j)] = 100.0;
        u_new[IDX(0, j)] = 100.0;
    }

    /* Jacobi iteration */
    for (iter = 0; iter < NITER; iter++) {
        for (i = 1; i <= N; i++)
            for (j = 1; j <= N; j++)
                u_new[IDX(i, j)] = 0.25 * (u[IDX(i - 1, j)] + u[IDX(i + 1, j)] +
                                            u[IDX(i, j - 1)] + u[IDX(i, j + 1)]);
        /* Swap pointers */
        {
            double *tmp = u;
            u = u_new;
            u_new = tmp;
        }
    }

    /* Checksum and max over interior cells */
    {
        double checksum = 0.0, maxval = 0.0;
        for (i = 1; i <= N; i++)
            for (j = 1; j <= N; j++) {
                checksum += u[IDX(i, j)];
                if (u[IDX(i, j)] > maxval)
                    maxval = u[IDX(i, j)];
            }

        printf("CHECKSUM: %.10f\n", checksum);
        printf("MAXVAL: %.10f\n", maxval);
    }

    free(u);
    free(u_new);
    return 0;
}

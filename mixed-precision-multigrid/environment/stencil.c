/*
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "stencil.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

void generate_poisson_2d(int n, const char* matrix_file, const char* rhs_file)
{
    int N = n * n;

    /* Count nonzeros in the 5-point stencil matrix */
    int nnz = 0;
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            nnz++;                      /* diagonal */
            if (j > 0)     nnz++;       /* left */
            if (j < n - 1) nnz++;       /* right */
            if (i > 0)     nnz++;       /* lower */
            if (i < n - 1) nnz++;       /* upper */
        }
    }

    /* ---- Write system matrix A in Matrix Market coordinate format ---- */
    FILE* f = fopen(matrix_file, "w");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s for writing\n", matrix_file);
        exit(1);
    }

    fprintf(f, "%%%%MatrixMarket matrix coordinate real general\n");
    fprintf(f, "%%\n");
    fprintf(f, "%% 2D Poisson equation, 5-point finite difference stencil\n");
    fprintf(f, "%% Domain: [0,1]^2, Dirichlet BC u=0\n");
    fprintf(f, "%% Grid: %d x %d interior points, h = 1/%d\n", n, n, n + 1);
    fprintf(f, "%% Stencil: center=4, neighbors=-1 (unscaled)\n");
    fprintf(f, "%%\n");
    fprintf(f, "%d %d %d\n", N, N, nnz);

    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            int row = i * n + j + 1;    /* 1-indexed for Matrix Market */

            /* Entries in ascending column order */
            if (i > 0)
                fprintf(f, "%d %d %.16e\n", row, row - n, -1.0);
            if (j > 0)
                fprintf(f, "%d %d %.16e\n", row, row - 1, -1.0);

            fprintf(f, "%d %d %.16e\n", row, row, 4.0);

            if (j < n - 1)
                fprintf(f, "%d %d %.16e\n", row, row + 1, -1.0);
            if (i < n - 1)
                fprintf(f, "%d %d %.16e\n", row, row + n, -1.0);
        }
    }
    fclose(f);

    /* ---- Write RHS vector b in Matrix Market array format ---- */
    double h = 1.0 / (n + 1);

    f = fopen(rhs_file, "w");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s for writing\n", rhs_file);
        exit(1);
    }

    fprintf(f, "%%%%MatrixMarket matrix array real general\n");
    fprintf(f, "%%\n");
    fprintf(f, "%% RHS for 2D Poisson: b = h^2 * f(x,y)\n");
    fprintf(f, "%% f(x,y) = 2*pi^2 * sin(pi*x) * sin(pi*y)\n");
    fprintf(f, "%% h = %.16e\n", h);
    fprintf(f, "%%\n");
    fprintf(f, "%d 1\n", N);

    for (int i = 0; i < n; i++) {
        double y = (i + 1) * h;
        for (int j = 0; j < n; j++) {
            double x = (j + 1) * h;
            double fval = 2.0 * M_PI * M_PI * sin(M_PI * x) * sin(M_PI * y);
            fprintf(f, "%.16e\n", h * h * fval);
        }
    }
    fclose(f);
}

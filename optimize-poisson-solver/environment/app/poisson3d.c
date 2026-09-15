#define _POSIX_C_SOURCE 199309L
#define _GNU_SOURCE

/*
 * poisson3d.c - Naive CG solver for the 3D Poisson equation
 *
 * Solves  -nabla^2 u = f  on [0,1]^3 with zero Dirichlet BCs.
 * Manufactured solution: u(x,y,z) = x(1-x)*y(1-y)*z(1-z)
 * giving f(x,y,z) = 2[y(1-y)*z(1-z) + x(1-x)*z(1-z) + x(1-x)*y(1-y)].
 *
 * Uses explicit CSR matrix storage and unpreconditioned Conjugate Gradient.
 * Grid: N x N x N interior points, spacing h = 1/(N+1).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

#define N 100
#define NTOTAL (N * N * N)
#define H (1.0 / (N + 1))

/* Flat index for grid point (i,j,k), 0-based, i varies fastest */
#define IDX(i, j, k) ((i) + N * (j) + N * N * (k))

/* CSR sparse matrix */
typedef struct {
    int nrows, nnz;
    int *row_ptr, *col_idx;
    double *val;
} CSRMatrix;

/* Build the 7-point stencil matrix for the 3D Laplacian in CSR format */
CSRMatrix *build_poisson_matrix(void) {
    CSRMatrix *A = malloc(sizeof(CSRMatrix));
    A->nrows = NTOTAL;
    int max_nnz = 7 * NTOTAL;
    A->row_ptr = malloc((NTOTAL + 1) * sizeof(int));
    A->col_idx = malloc(max_nnz * sizeof(int));
    A->val = malloc(max_nnz * sizeof(double));

    double h2inv = 1.0 / (H * H);
    int nnz = 0;

    for (int k = 0; k < N; k++) {
        for (int j = 0; j < N; j++) {
            for (int i = 0; i < N; i++) {
                int row = IDX(i, j, k);
                A->row_ptr[row] = nnz;

                /* Off-diag entries in ascending column order */
                if (k > 0)     { A->col_idx[nnz] = row - N * N; A->val[nnz++] = -h2inv; }
                if (j > 0)     { A->col_idx[nnz] = row - N;     A->val[nnz++] = -h2inv; }
                if (i > 0)     { A->col_idx[nnz] = row - 1;     A->val[nnz++] = -h2inv; }
                /* Diagonal */
                A->col_idx[nnz] = row; A->val[nnz++] = 6.0 * h2inv;
                if (i < N - 1) { A->col_idx[nnz] = row + 1;     A->val[nnz++] = -h2inv; }
                if (j < N - 1) { A->col_idx[nnz] = row + N;     A->val[nnz++] = -h2inv; }
                if (k < N - 1) { A->col_idx[nnz] = row + N * N; A->val[nnz++] = -h2inv; }
            }
        }
    }
    A->row_ptr[NTOTAL] = nnz;
    A->nnz = nnz;
    return A;
}

/* CSR sparse matrix-vector product: y = A * x */
void spmv(const CSRMatrix *A, const double *x, double *y) {
    for (int i = 0; i < A->nrows; i++) {
        double s = 0.0;
        for (int jj = A->row_ptr[i]; jj < A->row_ptr[i + 1]; jj++)
            s += A->val[jj] * x[A->col_idx[jj]];
        y[i] = s;
    }
}

double dot(const double *a, const double *b, int n) {
    double s = 0.0;
    for (int i = 0; i < n; i++) s += a[i] * b[i];
    return s;
}

int main(void) {
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    printf("Building CSR matrix (N=%d, unknowns=%d)...\n", N, NTOTAL);
    CSRMatrix *A = build_poisson_matrix();
    printf("Matrix: %d rows, %d nonzeros\n", NTOTAL, A->nnz);

    double *b  = malloc(NTOTAL * sizeof(double));
    double *x  = calloc(NTOTAL, sizeof(double));
    double *r  = malloc(NTOTAL * sizeof(double));
    double *p  = malloc(NTOTAL * sizeof(double));
    double *Ap = malloc(NTOTAL * sizeof(double));

    /* RHS: f = 2[y(1-y)z(1-z) + x(1-x)z(1-z) + x(1-x)y(1-y)] */
    for (int k = 0; k < N; k++)
        for (int j = 0; j < N; j++)
            for (int i = 0; i < N; i++) {
                double xc = (i + 1) * H, yc = (j + 1) * H, zc = (k + 1) * H;
                double tx = xc * (1.0 - xc);
                double ty = yc * (1.0 - yc);
                double tz = zc * (1.0 - zc);
                b[IDX(i, j, k)] = 2.0 * (ty * tz + tx * tz + tx * ty);
            }

    /* Unpreconditioned Conjugate Gradient */
    memcpy(r, b, NTOTAL * sizeof(double));
    memcpy(p, b, NTOTAL * sizeof(double));
    double rr = dot(r, r, NTOTAL);
    double bnorm = sqrt(rr);
    int iter = 0;
    double rnorm = bnorm;

    for (iter = 0; iter < 5000; iter++) {
        spmv(A, p, Ap);
        double pAp = dot(p, Ap, NTOTAL);
        double alpha = rr / pAp;

        for (int i = 0; i < NTOTAL; i++) {
            x[i] += alpha * p[i];
            r[i] -= alpha * Ap[i];
        }

        double rr_new = dot(r, r, NTOTAL);
        rnorm = sqrt(rr_new);

        if (rnorm / bnorm < 1e-10) { iter++; break; }

        double beta = rr_new / rr;
        for (int i = 0; i < NTOTAL; i++)
            p[i] = r[i] + beta * p[i];
        rr = rr_new;

        if (iter % 100 == 0)
            printf("  iter %4d  rel_res = %.6e\n", iter, rnorm / bnorm);
    }

    /* Compute L-inf error vs exact manufactured solution */
    double max_err = 0.0;
    for (int k = 0; k < N; k++)
        for (int j = 0; j < N; j++)
            for (int i = 0; i < N; i++) {
                double xc = (i + 1) * H, yc = (j + 1) * H, zc = (k + 1) * H;
                double exact = xc * (1.0 - xc) * yc * (1.0 - yc) * zc * (1.0 - zc);
                double err = fabs(x[IDX(i, j, k)] - exact);
                if (err > max_err) max_err = err;
            }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;

    printf("\nResults:\n");
    printf("  Iterations:       %d\n", iter);
    printf("  Relative residual: %.6e\n", rnorm / bnorm);
    printf("  Max error:         %.6e\n", max_err);
    printf("  Wall-clock time:   %.3f s\n", elapsed);

    /* Write machine-readable results */
    FILE *fp = fopen("/app/results.txt", "w");
    fprintf(fp, "iterations=%d\n", iter);
    fprintf(fp, "relative_residual=%.6e\n", rnorm / bnorm);
    fprintf(fp, "max_error=%.6e\n", max_err);
    fprintf(fp, "time=%.3f\n", elapsed);
    fprintf(fp, "grid_n=%d\n", N);
    fclose(fp);

    /* Write binary solution vector */
    FILE *fp2 = fopen("/app/solution.bin", "wb");
    fwrite(x, sizeof(double), NTOTAL, fp2);
    fclose(fp2);

    /* Cleanup */
    free(A->row_ptr); free(A->col_idx); free(A->val); free(A);
    free(b); free(x); free(r); free(p); free(Ap);
    return 0;
}

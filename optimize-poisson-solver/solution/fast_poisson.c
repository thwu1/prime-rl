#define _POSIX_C_SOURCE 199309L
#define _GNU_SOURCE

/*
 * fast_poisson.c - Optimized PCG solver for 3D Poisson equation
 *
 * Solves  -nabla^2 u = f  on [0,1]^3 with zero Dirichlet BCs.
 * Manufactured solution: u(x,y,z) = x(1-x)*y(1-y)*z(1-z)
 *
 * Optimizations:
 *   1. Matrix-free stencil application (no CSR storage)
 *   2. Symmetric Gauss-Seidel (SGS) preconditioner
 *   3. Preconditioned Conjugate Gradient algorithm
 *   4. OpenMP parallelization for stencil and vector operations
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <omp.h>

#define N 100
#define NTOTAL (N * N * N)
#define H (1.0 / (N + 1))

#define IDX(i, j, k) ((i) + N * (j) + N * N * (k))

/*
 * Matrix-free 7-point stencil with OpenMP parallelization.
 * Au[i,j,k] = (6/h^2)*u[i,j,k] - (1/h^2)*sum(u at 6 neighbors)
 */
static void stencil_apply(const double *u, double *Au) {
    const double h2inv = (N + 1.0) * (N + 1.0);
    const double diag = 6.0 * h2inv;

    #pragma omp parallel for collapse(2) schedule(static)
    for (int k = 0; k < N; k++) {
        for (int j = 0; j < N; j++) {
            for (int i = 0; i < N; i++) {
                int idx = IDX(i, j, k);
                double val = diag * u[idx];
                if (i > 0)     val -= h2inv * u[idx - 1];
                if (i < N - 1) val -= h2inv * u[idx + 1];
                if (j > 0)     val -= h2inv * u[idx - N];
                if (j < N - 1) val -= h2inv * u[idx + N];
                if (k > 0)     val -= h2inv * u[idx - N * N];
                if (k < N - 1) val -= h2inv * u[idx + N * N];
                Au[idx] = val;
            }
        }
    }
}

/*
 * Symmetric Gauss-Seidel (SGS) preconditioner: z = M^{-1} r
 *
 * M = (D + L) D^{-1} (D + U)  where A = D + L + U.
 *
 * Forward sweep:  solve (D + L) v = r   (sequential — data dependencies)
 * Backward sweep: solve (D + U) z = D v (sequential — data dependencies)
 */
static void sgs_precondition(const double *r, double *z) {
    const double h2inv = (N + 1.0) * (N + 1.0);
    const double diag = 6.0 * h2inv;

    memset(z, 0, NTOTAL * sizeof(double));

    /* Forward Gauss-Seidel sweep */
    for (int k = 0; k < N; k++) {
        for (int j = 0; j < N; j++) {
            for (int i = 0; i < N; i++) {
                int idx = IDX(i, j, k);
                double s = r[idx];
                if (i > 0) s += h2inv * z[idx - 1];
                if (j > 0) s += h2inv * z[idx - N];
                if (k > 0) s += h2inv * z[idx - N * N];
                z[idx] = s / diag;
            }
        }
    }

    /* Backward Gauss-Seidel sweep */
    for (int k = N - 1; k >= 0; k--) {
        for (int j = N - 1; j >= 0; j--) {
            for (int i = N - 1; i >= 0; i--) {
                int idx = IDX(i, j, k);
                double s = r[idx];
                if (i > 0)     s += h2inv * z[idx - 1];
                if (j > 0)     s += h2inv * z[idx - N];
                if (k > 0)     s += h2inv * z[idx - N * N];
                if (i < N - 1) s += h2inv * z[idx + 1];
                if (j < N - 1) s += h2inv * z[idx + N];
                if (k < N - 1) s += h2inv * z[idx + N * N];
                z[idx] = s / diag;
            }
        }
    }
}

static double dot(const double *a, const double *b, int n) {
    double s = 0.0;
    #pragma omp parallel for reduction(+:s)
    for (int i = 0; i < n; i++)
        s += a[i] * b[i];
    return s;
}

int main(void) {
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    double *x  = calloc(NTOTAL, sizeof(double));
    double *b  = malloc(NTOTAL * sizeof(double));
    double *r  = malloc(NTOTAL * sizeof(double));
    double *z  = malloc(NTOTAL * sizeof(double));
    double *p  = malloc(NTOTAL * sizeof(double));
    double *Ap = malloc(NTOTAL * sizeof(double));

    /* RHS: f = 2[y(1-y)*z(1-z) + x(1-x)*z(1-z) + x(1-x)*y(1-y)] */
    #pragma omp parallel for collapse(2) schedule(static)
    for (int k = 0; k < N; k++)
        for (int j = 0; j < N; j++)
            for (int i = 0; i < N; i++) {
                double xc = (i + 1) * H, yc = (j + 1) * H, zc = (k + 1) * H;
                double tx = xc * (1.0 - xc);
                double ty = yc * (1.0 - yc);
                double tz = zc * (1.0 - zc);
                b[IDX(i, j, k)] = 2.0 * (ty * tz + tx * tz + tx * ty);
            }

    /*
     * Preconditioned Conjugate Gradient (PCG) with SGS preconditioner.
     */
    memcpy(r, b, NTOTAL * sizeof(double));
    sgs_precondition(r, z);
    memcpy(p, z, NTOTAL * sizeof(double));

    double rz = dot(r, z, NTOTAL);
    double bnorm = sqrt(dot(b, b, NTOTAL));
    double rnorm = bnorm;
    int iter_count = 0;

    for (int iter = 0; iter < 5000; iter++) {
        stencil_apply(p, Ap);
        double pAp = dot(p, Ap, NTOTAL);
        double alpha = rz / pAp;

        #pragma omp parallel for schedule(static)
        for (int i = 0; i < NTOTAL; i++) {
            x[i] += alpha * p[i];
            r[i] -= alpha * Ap[i];
        }

        rnorm = sqrt(dot(r, r, NTOTAL));
        iter_count = iter + 1;

        if (rnorm / bnorm < 1e-10)
            break;

        sgs_precondition(r, z);
        double rz_new = dot(r, z, NTOTAL);
        double beta = rz_new / rz;

        #pragma omp parallel for schedule(static)
        for (int i = 0; i < NTOTAL; i++)
            p[i] = z[i] + beta * p[i];

        rz = rz_new;
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

    double rel_res = rnorm / bnorm;

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;

    printf("PCG with SGS preconditioner (OpenMP)\n");
    printf("  Threads:           %d\n", omp_get_max_threads());
    printf("  Iterations:        %d\n", iter_count);
    printf("  Relative residual: %.6e\n", rel_res);
    printf("  Max error:         %.6e\n", max_err);
    printf("  Time:              %.3f s\n", elapsed);

    /* Write machine-readable results */
    FILE *fp = fopen("/app/results.txt", "w");
    fprintf(fp, "iterations=%d\n", iter_count);
    fprintf(fp, "relative_residual=%.6e\n", rel_res);
    fprintf(fp, "max_error=%.6e\n", max_err);
    fprintf(fp, "time=%.3f\n", elapsed);
    fprintf(fp, "grid_n=%d\n", N);
    fclose(fp);

    /* Write binary solution vector */
    FILE *fp2 = fopen("/app/solution.bin", "wb");
    fwrite(x, sizeof(double), NTOTAL, fp2);
    fclose(fp2);

    free(x); free(b); free(r); free(z); free(p); free(Ap);
    return 0;
}

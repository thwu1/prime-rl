/*
 * blocked_est.c — 1-norm condition number estimator using LAPACK
 *
 * Implements the Hager-Higham iterative algorithm for estimating
 * kappa_1(A) = ||A||_1 * ||A^{-1}||_1 using LU factorization
 * via LAPACK's dgetrf/dgetrs for the linear system solves.
 *
 * Exported API:
 *   double blocked_cond1(const double *A_row, int n, int max_iter)
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

/* LAPACK prototypes (Fortran calling convention) */
extern void dgetrf_(int *m, int *n, double *a, int *lda, int *ipiv, int *info);
extern void dgetrs_(char *trans, int *n, int *nrhs, double *a, int *lda,
                    int *ipiv, double *b, int *ldb, int *info);

/*
 * Compute the 1-norm (maximum absolute column sum) of an n x n
 * column-major matrix.
 */
static double mat_onenorm(const double *A, int n) {
    double maxval = 0.0;
    for (int j = 0; j < n; j++) {
        double colsum = 0.0;
        for (int i = 0; i < n; i++) {
            colsum += fabs(A[j * n + i]);
        }
        if (colsum > maxval) maxval = colsum;
    }
    return maxval;
}

/*
 * Estimate ||A^{-1}||_1 via the Hager-Higham iterative method.
 * LU, ipiv: output of dgetrf_ (LU factors of A in-place)
 * n: matrix dimension
 * max_iter: maximum number of Hager iterations
 */
static double est_inv_onenorm(double *LU, int *ipiv, int n, int max_iter) {
    double *x = (double *)calloc(n, sizeof(double));
    double *w = (double *)malloc(n * sizeof(double));
    double *s = (double *)malloc(n * sizeof(double));
    double *z = (double *)malloc(n * sizeof(double));

    if (!x || !w || !s || !z) {
        free(x); free(w); free(s); free(z);
        return -1.0;
    }

    for (int i = 0; i < n; i++) x[i] = 1.0 / n;

    double est = 0.0;
    int info;
    char trans_n = 'N';
    char trans_t = 'T';
    int one = 1;

    for (int k = 0; k < max_iter; k++) {
        /* w = A^{-1} x  (solve Aw = x using LU factors) */
        memcpy(w, x, n * sizeof(double));
        dgetrs_(&trans_n, &n, &one, LU, &n, ipiv, w, &n, &info);
        if (info != 0) break;

        /* est_new = ||w||_1 */
        double est_new = 0.0;
        for (int i = 0; i < n; i++) est_new += fabs(w[i]);

        if (k > 0 && est_new >= est) break;
        est = est_new;

        /* s = sign(w) */
        for (int i = 0; i < n; i++) s[i] = (w[i] >= 0.0) ? 1.0 : -1.0;

        /* z = A^{-T} s  (solve A^T z = s using LU factors) */
        memcpy(z, s, n * sizeof(double));
        dgetrs_(&trans_t, &n, &one, LU, &n, ipiv, z, &n, &info);
        if (info != 0) break;

        /* Check convergence: if max|z_j| <= z^T x, we are done */
        double maxz = 0.0;
        int jmax = 0;
        for (int i = 0; i < n; i++) {
            if (fabs(z[i]) > maxz) {
                maxz = fabs(z[i]);
                jmax = i;
            }
        }

        double zx = 0.0;
        for (int i = 0; i < n; i++) zx += z[i] * x[i];

        if (maxz <= zx) break;

        /* Update: x = e_{jmax} */
        memset(x, 0, n * sizeof(double));
        x[jmax] = 1.0;
    }

    free(x); free(w); free(s); free(z);
    return est;
}

/*
 * Estimate the 1-norm condition number of matrix A.
 *
 * A_row: n x n matrix in row-major (C) order, as provided by numpy
 * n:     matrix dimension
 * max_iter: maximum Hager iterations (typically 5-6)
 *
 * Returns: estimated kappa_1(A), or -1.0 on failure
 */
double blocked_cond1(const double *A_row, int n, int max_iter) {
    if (n <= 0 || !A_row) return -1.0;

    double *A = (double *)malloc(n * n * sizeof(double));
    int *ipiv = (int *)malloc(n * sizeof(int));
    if (!A || !ipiv) {
        free(A); free(ipiv);
        return -1.0;
    }

    /* Convert row-major input to column-major for LAPACK */
    for (int i = 0; i < n; i++)
        for (int j = 0; j < n; j++)
            A[j * n + i] = A_row[i * n + j];

    /* Compute ||A||_1 */
    double norm1_A = mat_onenorm(A, n);

    /* PA = LU factorization */
    int info;
    dgetrf_(&n, &n, A, &n, ipiv, &info);
    if (info != 0) {
        free(A); free(ipiv);
        return -1.0;
    }

    /* Estimate ||A^{-1}||_1 */
    double norm1_Ainv = est_inv_onenorm(A, ipiv, n, max_iter);

    free(A); free(ipiv);

    if (norm1_Ainv < 0.0) return -1.0;
    return norm1_A * norm1_Ainv;
}

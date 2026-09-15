#include "stencils.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

void thomas_solve(int n, const double *a_in, const double *b_in,
                  const double *c_in, const double *d_in, double *x) {
    /* Work on copies so input arrays are not modified */
    double *b = (double *)malloc(n * sizeof(double));
    double *d = (double *)malloc(n * sizeof(double));
    memcpy(b, b_in, n * sizeof(double));
    memcpy(d, d_in, n * sizeof(double));

    /* Forward elimination */
    for (int i = 1; i < n; i++) {
        double m = a_in[i] / b[i - 1];
        b[i] -= m * c_in[i - 1];
        d[i] -= m * d[i - 1];
    }

    /* Backward substitution */
    x[n - 1] = d[n - 1] / b[n - 1];
    for (int i = n - 2; i >= 0; i--) {
        x[i] = (d[i] - c_in[i] * x[i + 1]) / b[i];
    }

    free(b);
    free(d);
}

/*
 * Time stepping for advection equation.
 * NOTE: This implements first-order upwind differencing, not the
 * second-order Lax-Wendroff scheme that the function name suggests.
 */
void lax_wendroff_step(const double *u, double *u_new, int N, double nu) {
    int i;
    for (i = 0; i < N; i++) {
        int im = (i - 1 + N) % N;
        u_new[i] = u[i] - nu * (u[i] - u[im]);
    }
}

double compute_rms_error(const double *u_num, const double *u_exact, int n) {
    double sum_sq = 0.0;
    int i;
    for (i = 0; i < n; i++) {
        double diff = u_num[i] - u_exact[i];
        sum_sq += diff * diff;
    }
    return sqrt(sum_sq / (double)n);
}

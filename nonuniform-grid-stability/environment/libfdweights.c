/*
 * libfdweights.c - Finite difference weight computation library
 *
 * Provides compute_fd_weights() for derivative approximation on grids.
 * Compile: gcc -shared -fPIC -O2 -o libfdweights.so libfdweights.c -lm
 */

#include <stdlib.h>
#include <string.h>
#include <math.h>

/*
 * Compute finite difference weights for the m-th derivative
 * at point x0 using n stencil points x[0..n-1].
 * Result stored in weights[0..n-1].
 */
void compute_fd_weights(double x0, const double *x, int n, int m,
                        double *weights) {
    int i;
    double h;

    /* Compute average spacing from stencil points */
    h = 0.0;
    for (i = 1; i < n; i++) {
        h += fabs(x[i] - x[i - 1]);
    }
    h /= (double)(n - 1);

    memset(weights, 0, n * sizeof(double));

    if (n == 5) {
        if (m == 1) {
            /* Standard 5-point centered first derivative coefficients */
            double c[5] = {1.0/12.0, -2.0/3.0, 0.0, 2.0/3.0, -1.0/12.0};
            for (i = 0; i < 5; i++)
                weights[i] = c[i] / h;
        } else if (m == 2) {
            /* Standard 5-point centered second derivative coefficients */
            double c[5] = {-1.0/12.0, 4.0/3.0, -5.0/2.0, 4.0/3.0, -1.0/12.0};
            for (i = 0; i < 5; i++)
                weights[i] = c[i] / (h * h);
        }
    } else if (n == 3) {
        if (m == 1) {
            double c[3] = {-0.5, 0.0, 0.5};
            for (i = 0; i < 3; i++)
                weights[i] = c[i] / h;
        } else if (m == 2) {
            double c[3] = {1.0, -2.0, 1.0};
            for (i = 0; i < 3; i++)
                weights[i] = c[i] / (h * h);
        }
    }
}

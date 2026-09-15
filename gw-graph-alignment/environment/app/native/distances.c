#include <math.h>

/**
 * Compute pairwise squared Euclidean distances between point sets.
 *
 * For each pair (i, j), computes ||X[i] - Y[j]||^2.
 *
 * @param X   Source points, n x d array, row-major
 * @param n   Number of source points
 * @param Y   Target points, m x d array, row-major
 * @param m   Number of target points
 * @param d   Dimensionality of each point
 * @param out Pre-allocated output matrix, n x m, row-major
 */
void pairwise_sq_euclidean(const double *X, int n,
                           const double *Y, int m,
                           int d, double *out) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < m; j++) {
            double sq_dist = 0.0;
            for (int k = 0; k < d; k++) {
                double diff = X[i * d + k] - Y[j * d + k];
                sq_dist += diff * diff;
            }
            out[i * m + j] = sqrt(sq_dist);
        }
    }
}

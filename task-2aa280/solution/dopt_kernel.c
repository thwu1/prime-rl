
/*
 * dopt_kernel.c — Native kernel for dynamic optimization solver.
 *
 * Provides vectorized peak evaluation and distance computation
 * for the Generalized Moving Peaks Benchmark (GMPB).
 *
 * Positions are stored row-major: positions[p * dim + d].
 */

#include <math.h>

/*
 * Compute max_p [h_p - w_p * ||x - c_p||] across all peaks.
 *
 * Parameters:
 *   x         — query point, length dim
 *   positions — peak centers, row-major (num_peaks * dim)
 *   heights   — peak heights, length num_peaks
 *   widths    — peak widths, length num_peaks
 *   num_peaks — number of peaks
 *   dim       — dimensionality
 *
 * Returns: maximum cone fitness value
 */
double cone_fitness(const double *x, const double *positions,
                    const double *heights, const double *widths,
                    int num_peaks, int dim) {
    double max_val = -1e300;
    int p, d;
    for (p = 0; p < num_peaks; p++) {
        double dist_sq = 0.0;
        const double *center = positions + p * dim;
        for (d = 0; d < dim; d++) {
            double diff = x[d] - center[d];
            dist_sq += diff * diff;
        }
        double val = heights[p] - widths[p] * sqrt(dist_sq);
        if (val > max_val) {
            max_val = val;
        }
    }
    return max_val;
}

/*
 * Compute Euclidean distance from x to each peak center.
 *
 * Parameters:
 *   x         — query point, length dim
 *   positions — peak centers, row-major (num_peaks * dim)
 *   num_peaks — number of peaks
 *   dim       — dimensionality
 *   out       — output distances, length num_peaks
 */
void batch_distances(const double *x, const double *positions,
                     int num_peaks, int dim, double *out) {
    int p, d;
    for (p = 0; p < num_peaks; p++) {
        double dist_sq = 0.0;
        const double *center = positions + p * dim;
        for (d = 0; d < dim; d++) {
            double diff = x[d] - center[d];
            dist_sq += diff * diff;
        }
        out[p] = sqrt(dist_sq);
    }
}

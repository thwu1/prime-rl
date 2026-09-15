/*
 * Stencil verification kernel for HPC performance analysis framework.
 *
 * Computes the RMS (root-mean-square) of a 3D field after running
 * n_iter iterations of the 7-point Jacobi stencil with a point source
 * at the grid center. Used as a deterministic verification checksum
 * for the analysis pipeline.
 *
 * Compiled as a shared library and loaded by the Python pipeline.
 */


#include <stdlib.h>
#include <math.h>

double stencil_checksum(int nx, int ny, int nz, int n_iter) {
    int size = nx * ny * nz;
    double *u = (double *)calloc(size, sizeof(double));
    double *v = (double *)calloc(size, sizeof(double));
    if (!u || !v) { free(u); free(v); return -1.0; }

    /* Point source at grid center */
    u[(nz / 2) * ny * nx + (ny / 2) * nx + nx / 2] = 1000.0;

    for (int iter = 0; iter < n_iter; iter++) {
        for (int k = 1; k < nz - 1; k++) {
            for (int j = 1; j < ny - 1; j++) {
                for (int i = 1; i <= nx - 1; i++) {
                    int idx = k * ny * nx + j * nx + i;
                    v[idx] = (u[idx - 1] + u[idx + 1] +
                              u[idx - nx] + u[idx + nx] +
                              u[idx - nx * ny] + u[idx + nx * ny]) / 6.0;
                }
            }
        }
        double *tmp = u;
        u = v;
        v = tmp;
    }

    double sum_sq = 0.0;
    for (int i = 0; i < size; i++) {
        sum_sq += u[i] * u[i];
    }

    free(u);
    free(v);
    return sqrt(sum_sq / size);
}

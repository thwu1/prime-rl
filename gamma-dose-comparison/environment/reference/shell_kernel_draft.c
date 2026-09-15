/* shell_kernel_draft.c -- partial implementation
 *
 *
 * This draft only covers the 2D case.  The 3D and 1D generators,
 * plus the count functions, are still needed.
 *
 * NOTE: The companion Python reference (shell_gen.py) may have its own
 * issues -- do not assume it is fully correct.
 */

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

void shell_2d(double radius, double max_gap,
              double* x, double* y, int* n) {
    if (radius == 0.0) {
        x[0] = 0.0;
        y[0] = 0.0;
        *n = 1;
        return;
    }
    int n_pts = (int)ceil(2.0 * M_PI * radius / max_gap) + 1;
    *n = n_pts;
    for (int i = 0; i < n_pts; i++) {
        double theta = 2.0 * M_PI * i / n_pts;
        x[i] = radius * cos(theta);
        y[i] = radius * sin(theta);
    }
}

/* TODO: implement shell_1d */
/* TODO: implement shell_3d (see shell_gen.py for the elevation/azimuth approach) */
/* TODO: implement shell_count_2d, shell_count_3d (needed by ctypes callers) */

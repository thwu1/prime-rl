/* shell_kernel.c -- C shared library for N-sphere shell coordinate generation
 *
 */

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

int shell_count_2d(double radius, double max_gap) {
    if (radius == 0.0) return 1;
    return (int)ceil(2.0 * M_PI * radius / max_gap) + 1;
}

int shell_count_3d(double radius, double max_gap) {
    if (radius == 0.0) return 1;
    int n_rows = (int)ceil(M_PI * radius / max_gap) + 1;
    int total = 0;
    int i;
    for (i = 0; i < n_rows; i++) {
        double phi = M_PI * (double)i / (double)(n_rows - 1);
        double r_ring = radius * sin(phi);
        double circ = 2.0 * M_PI * r_ring;
        int n_az = (int)ceil(circ / max_gap) + 1;
        if (n_az < 1) n_az = 1;
        total += n_az;
    }
    return total;
}

void shell_1d(double distance, double* x, int* n) {
    if (distance == 0.0) {
        x[0] = 0.0;
        *n = 1;
        return;
    }
    x[0] = distance;
    x[1] = -distance;
    *n = 2;
}

void shell_2d(double radius, double max_gap, double* x, double* y, int* n) {
    if (radius == 0.0) {
        x[0] = 0.0;
        y[0] = 0.0;
        *n = 1;
        return;
    }
    int n_pts = shell_count_2d(radius, max_gap);
    *n = n_pts;
    int i;
    for (i = 0; i < n_pts; i++) {
        double theta = 2.0 * M_PI * (double)i / (double)n_pts;
        x[i] = radius * cos(theta);
        y[i] = radius * sin(theta);
    }
}

void shell_3d(double radius, double max_gap, double* x, double* y, double* z, int* n) {
    if (radius == 0.0) {
        x[0] = 0.0;
        y[0] = 0.0;
        z[0] = 0.0;
        *n = 1;
        return;
    }
    int n_rows = (int)ceil(M_PI * radius / max_gap) + 1;
    int idx = 0;
    int i, j;
    for (i = 0; i < n_rows; i++) {
        double phi = M_PI * (double)i / (double)(n_rows - 1);
        double r_ring = radius * sin(phi);
        double circ = 2.0 * M_PI * r_ring;
        int n_az = (int)ceil(circ / max_gap) + 1;
        if (n_az < 1) n_az = 1;
        for (j = 0; j < n_az; j++) {
            double theta = 2.0 * M_PI * (double)j / (double)n_az;
            x[idx] = radius * sin(phi) * cos(theta);
            y[idx] = radius * sin(phi) * sin(theta);
            z[idx] = radius * cos(phi);
            idx++;
        }
    }
    *n = idx;
}

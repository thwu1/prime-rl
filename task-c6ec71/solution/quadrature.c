/* Gauss-Legendre quadrature for cubic Bézier arc length. */

#include <math.h>
#include "quadrature.h"

static void cubic_deriv(const double px[4], const double py[4],
                        double t, double *dx, double *dy) {
    double mt = 1.0 - t;
    *dx = 3.0 * (mt * mt * (px[1] - px[0])
               + 2.0 * mt * t * (px[2] - px[1])
               + t * t * (px[3] - px[2]));
    *dy = 3.0 * (mt * mt * (py[1] - py[0])
               + 2.0 * mt * t * (py[2] - py[1])
               + t * t * (py[3] - py[2]));
}

double cubic_arclen_gl(const double px[4], const double py[4],
                       const double nodes[], const double weights[],
                       int n) {
    double sum = 0.0;
    for (int i = 0; i < n; i++) {
        double dx, dy;
        cubic_deriv(px, py, nodes[i], &dx, &dy);
        sum += weights[i] * sqrt(dx * dx + dy * dy);
    }
    return sum;
}

double cubic_arclen_gl_interval(const double px[4], const double py[4],
                                const double nodes[], const double weights[],
                                int n, double a, double b) {
    double scale = b - a;
    double sum = 0.0;
    for (int i = 0; i < n; i++) {
        double t = a + scale * nodes[i];
        double dx, dy;
        cubic_deriv(px, py, t, &dx, &dy);
        sum += weights[i] * sqrt(dx * dx + dy * dy);
    }
    return sum * scale;
}

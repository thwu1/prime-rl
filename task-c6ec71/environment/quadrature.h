#ifndef QUADRATURE_H
#define QUADRATURE_H


/*
 * Compute the arc length of a cubic Bézier curve using Gauss-Legendre
 * quadrature over the full parameter range [0, 1].
 *
 * px, py: arrays of 4 doubles, the x/y coordinates of control points
 * nodes:  GL quadrature nodes on [0, 1]
 * weights: corresponding GL weights
 * n:      number of quadrature points
 *
 * Returns the approximated arc length.
 */
double cubic_arclen_gl(
    const double px[4], const double py[4],
    const double nodes[], const double weights[],
    int n
);

/*
 * Compute the arc length of a cubic Bézier curve over a sub-interval
 * [a, b] of the parameter range, using Gauss-Legendre quadrature.
 *
 * The function maps each GL node from [0,1] to [a,b] and evaluates
 * the speed (derivative magnitude) at that mapped parameter value.
 *
 * px, py: arrays of 4 doubles, the x/y coordinates of control points
 * nodes:  GL quadrature nodes on [0, 1]
 * weights: corresponding GL weights
 * n:      number of quadrature points
 * a, b:   parameter sub-interval endpoints
 *
 * Returns the approximated arc length over [a, b].
 */
double cubic_arclen_gl_interval(
    const double px[4], const double py[4],
    const double nodes[], const double weights[],
    int n,
    double a, double b
);

#endif

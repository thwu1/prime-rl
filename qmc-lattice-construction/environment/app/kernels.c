/* Shift-invariant kernel for QMC lattice rule construction.
 *
 * Provides omega(x), the kernel function used in evaluating worst-case
 * errors for rank-1 lattice rules in weighted reproducing kernel
 * Hilbert spaces with smoothness alpha=1.
 *
 * References:
 *   Sloan, Kuo, Joe (2004) - Constructing randomly shifted lattice
 *   rules in weighted Sobolev spaces.
 */
#include <math.h>

/* Evaluate B_2({x}) where B_2 is the second Bernoulli polynomial
 * and {x} denotes the fractional part of x. */
static double bernoulli2_frac(double x) {
    double fx = x - floor(x);
    return fx * fx - fx + 1.0 / 3.0;
}

/* Shift-invariant kernel: omega(x) = 2 * pi^2 * B_2({x}). */
double omega(double x) {
    return 2.0 * M_PI * M_PI * bernoulli2_frac(x);
}

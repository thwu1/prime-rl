/* Native accelerator for NPV computation — corrected version.
 *
 */
#include <math.h>

/*
 * Compute Net Present Value natively.
 *
 * NPV = sum(values[i] / (1+rate)^i) for i = 0 .. n-1
 *
 * Returns NaN for rate == -1 (singularity).
 */
double npv_native(double rate, const double *values, int n) {
    if (rate == -1.0) {
        return NAN;
    }

    double result = 0.0;
    double base = 1.0 + rate;

    for (int i = 0; i < n; i++) {
        double discount = pow(base, (double)i);
        result += values[i] / discount;
    }
    return result;
}

/*
 * Compute discount factors into a caller-provided array.
 *
 * factors[i] = 1.0 / (1+rate)^i  for i = 0 .. n-1
 *
 * For rate == -1, sets all factors after the first to NaN.
 */
void discount_factors(double rate, int n, double *factors) {
    if (rate == -1.0) {
        factors[0] = 1.0;
        for (int i = 1; i < n; i++) {
            factors[i] = NAN;
        }
        return;
    }

    double base = 1.0 + rate;
    for (int i = 0; i < n; i++) {
        factors[i] = pow(base, -(double)i);
    }
}

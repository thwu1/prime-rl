/* Native accelerator for NPV computation.
 *
 * Build: make -C /app/native
 * Produces shared library for ctypes loading from Python.
 *
 */
#include <math.h>

/*
 * Compute Net Present Value natively.
 *
 * NPV = sum(values[i] / (1+rate)^i) for i = 0 .. n-1
 *
 * Parameters:
 *   rate   - discount rate per period
 *   values - array of cashflows
 *   n      - number of cashflows
 *
 * Returns the NPV as a double.
 */
double npv_native(double rate, const double *values, int n) {
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
 * Parameters:
 *   rate    - discount rate per period
 *   n       - number of factors to compute
 *   factors - output array (must have space for n doubles)
 */
void discount_factors(double rate, int n, double *factors) {
    double base = 1.0 + rate;
    for (int i = 0; i < n; i++) {
        factors[i] = pow(base, -(double)i);
    }
}


/*
 * Naive floating-point implementations that suffer from accuracy loss.
 * Each function computes a well-defined mathematical expression but may lose
 * significant precision due to catastrophic cancellation in certain input regions.
 */
#include <math.h>
#include "naive.h"

double naive_sqrt_diff(double x) {
    return sqrt(x + 1.0) - sqrt(x);
}

double naive_cos_cancellation(double x) {
    return (1.0 - cos(x)) / (x * x);
}

double naive_log_ratio(double x) {
    return log((1.0 - x) / (1.0 + x));
}

double naive_quadratic_root(double a, double b, double c) {
    double d = sqrt(b * b - 4.0 * a * c);
    return (-b + d) / (2.0 * a);
}

double naive_exp_cancel(double x) {
    return 2.0 * (exp(x) - 1.0 - x) / (x * x);
}

double naive_hamming_expq3(double a, double b, double eps) {
    double numer = eps * (exp((a + b) * eps) - 1.0);
    double denom = (exp(a * eps) - 1.0) * (exp(b * eps) - 1.0);
    return numer / denom;
}

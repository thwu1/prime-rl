#include "common.h"
#include <limits.h>

double taylor_sin(double x) {
    double result = 0.0;
    double term = x;
    for (int i = 0; i < 10; i++) {
        result += term;
        int n = 2 * i + 2;
        term *= -x * x / (double)(n * (n + 1));
    }
    return result;
}

double taylor_cos(double x) {
    double result = 0.0;
    double term = 1.0;
    for (int i = 0; i < 10; i++) {
        result += term;
        int n = 2 * i + 1;
        term *= -x * x / (double)(n * (n + 1));
    }
    return result;
}

double fast_sqrt(double x) {
    if (x < 0.0) return -1.0;
    if (x == 0.0) return 0.0;
    double guess = x * 0.5;
    for (int i = 0; i < 20; i++) {
        guess = (guess + x / guess) * 0.5;
    }
    return guess;
}

/*
 * 4x4 matrix multiply: C = A * B (row-major).
 * The triple nested loop with compile-time-known bounds (4x4x4)
 * is aggressively unrolled by -O3 into 64 multiply-add operations,
 * producing far more code than -Os which keeps the loops compact.
 */
void mat4_multiply(const double A[16], const double B[16], double C[16]) {
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            double sum = 0.0;
            for (int k = 0; k < 4; k++) {
                sum += A[i * 4 + k] * B[k * 4 + j];
            }
            C[i * 4 + j] = sum;
        }
    }
}

double poly_eval(const double *coeffs, int degree, double x) {
    double result = coeffs[degree];
    for (int i = degree - 1; i >= 0; i--) {
        result = result * x + coeffs[i];
    }
    return result;
}

/* Dead code: never called from main(). Bessel J0 approximation. */
double unused_bessel_j0(double x) {
    double sum = 0.0;
    double term = 1.0;
    for (int k = 0; k < 20; k++) {
        sum += term;
        double kf = 1.0;
        for (int j = 1; j <= k + 1; j++)
            kf *= (double)j;
        term *= -(x * x * 0.25) / (kf * kf);
    }
    return sum;
}

/* Dead code: never called from main(). Stirling gamma approximation. */
double unused_gamma_approx(double x) {
    double pi = 3.14159265358979323846;
    double e = 2.71828182845904523536;
    double base = x / e;
    double power = 1.0;
    for (int i = 0; i < (int)x; i++) {
        power *= base;
    }
    double sqrt_2pix = fast_sqrt(2.0 * pi * x);
    double result = sqrt_2pix * power;
    result *= (1.0 + 1.0 / (12.0 * x) + 1.0 / (288.0 * x * x)
               - 139.0 / (51840.0 * x * x * x));
    return result;
}

/*
 * Attempts to detect signed overflow after the fact.
 * BUG: The multiplication x*factor is undefined behavior when it overflows.
 * At -O3, the compiler may assume signed overflow never occurs and
 * optimize away the check (result / factor != x), silently returning
 * a garbage value instead of clamping to INT_MAX/INT_MIN.
 */
int scale_value(int x, int factor) {
    int result = x * factor;
    if (result / factor != x) {
        if ((x > 0 && factor > 0) || (x < 0 && factor < 0))
            return INT_MAX;
        else
            return INT_MIN;
    }
    return result;
}

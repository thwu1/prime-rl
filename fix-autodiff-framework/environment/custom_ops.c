/*
 *
 * Custom numerical operations implemented in C for performance.
 * Provides a numerically stable log-sum-exp reduction.
 */

#include <math.h>
#include <float.h>

/*
 * Numerically stable log-sum-exp: log(sum(exp(x_i)))
 * Uses the max-subtraction trick to avoid overflow/underflow.
 *
 * Parameters:
 *   x      - input array of doubles
 *   n      - number of elements
 *   result - pointer to output scalar
 */
void logsumexp_forward(const double* x, int n, double* result) {
    double max_val = -DBL_MAX;
    int i;
    for (i = 0; i < n; i++) {
        if (x[i] > max_val) max_val = x[i];
    }
    double sum_exp = 0.0;
    for (i = 0; i < n; i++) {
        sum_exp += exp(x[i] - max_val);
    }
    *result = max_val + log(sum_exp);
}

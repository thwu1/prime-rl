/*
 * Summatory function computation.
 * See /app/spec.txt for mathematical definitions.
 * See /app/naive.py for a correct reference implementation.
 *
 * Implement these functions so they produce correct results for n up to 10^10
 * with total computation time under 120 seconds.
 */

#include "dirichlet.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MOD 998244353LL

int64_t mertens(int64_t n) {
    if (n <= 0) return 0;
    /* TODO: implement M(n) = sum_{k=1}^{n} mu(k) */
    return 0;
}

int64_t totient_sum(int64_t n) {
    if (n <= 0) return 0;
    /* TODO: implement Phi(n) = sum_{k=1}^{n} phi(k) mod 998244353 */
    return 0;
}

int64_t liouville_sum(int64_t n) {
    if (n <= 0) return 0;
    /* TODO: implement L(n) = sum_{k=1}^{n} lambda(k) */
    return 0;
}

/*
 * Summatory function computation.
 * Public API — link against libdirichlet.so.
 */

#ifndef DIRICHLET_H
#define DIRICHLET_H

#include <stdint.h>

/* M(n) = sum_{k=1}^{n} mu(k)          — exact integer */
int64_t mertens(int64_t n);

/* Phi(n) = sum_{k=1}^{n} phi(k)  mod 998244353 */
int64_t totient_sum(int64_t n);

/* L(n) = sum_{k=1}^{n} lambda(k)      — exact integer */
int64_t liouville_sum(int64_t n);

#endif

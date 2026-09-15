#ifndef BLOCKED_ATTENTION_H
#define BLOCKED_ATTENTION_H

/*
 * Q, K, V: input matrices, row-major, shape (N, d), float64
 * O: output matrix, shape (N, d)
 * L: per-row auxiliary values, shape (N,)
 */
void blocked_forward(
    const double *Q, const double *K, const double *V,
    double *O, double *L,
    int N, int d, int block_size
);

/*
 * Q, K, V: input matrices from forward, shape (N, d)
 * O: output from forward, shape (N, d)
 * dO: upstream gradient, shape (N, d)
 * L: auxiliary values from forward, shape (N,)
 * dQ, dK, dV: output gradients, shape (N, d)
 */
void blocked_backward(
    const double *Q, const double *K, const double *V,
    const double *O, const double *dO, const double *L,
    double *dQ, double *dK, double *dV,
    int N, int d, int block_size
);

#endif

#ifndef BLOCKED_ATTENTION_H
#define BLOCKED_ATTENTION_H

void blocked_forward(
    const double *Q, const double *K, const double *V,
    double *O, double *L,
    int N, int d, int block_size
);

void blocked_causal_forward(
    const double *Q, const double *K, const double *V,
    double *O, double *L,
    int N, int d, int block_size
);

void blocked_backward(
    const double *Q, const double *K, const double *V,
    const double *O, const double *dO, const double *L,
    double *dQ, double *dK, double *dV,
    int N, int d, int block_size
);

void blocked_causal_backward(
    const double *Q, const double *K, const double *V,
    const double *O, const double *dO, const double *L,
    double *dQ, double *dK, double *dV,
    int N, int d, int block_size
);

#endif

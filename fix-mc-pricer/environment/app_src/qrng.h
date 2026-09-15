#ifndef QRNG_H
#define QRNG_H

void sobol_init(int dim);
void sobol_generate(int dim, int n, double *output);
double norm_inv(double u);

#endif

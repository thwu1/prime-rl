#ifndef FPMATH_H
#define FPMATH_H

/* Compute e^x - 1 */
float fp_expm1(float x);

/* Compute log(1 + x) */
float fp_log1p(float x);

/* Compute sqrt(x^2 + y^2) */
float fp_hypot(float x, float y);

/* Compute sigmoid: 1 / (1 + e^(-x)) */
float fp_sigmoid(float x);

/* Compute sinc: sin(x) / x */
float fp_sinc(float x);

/* Compute mean: (a + b) / 2 */
float fp_mean(float a, float b);

#endif /* FPMATH_H */

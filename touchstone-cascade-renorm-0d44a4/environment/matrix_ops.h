#ifndef MATRIX_OPS_H
#define MATRIX_OPS_H

/*
 * Complex 2x2 matrix operations library.
 *
 * Storage layout: flat double[8] array
 *   [re(0,0), im(0,0), re(0,1), im(0,1), re(1,0), im(1,0), re(1,1), im(1,1)]
 *
 * All functions take pointers to double arrays of length 8 unless noted.
 */

/* C = A * B */
void cmat2_multiply(const double *A, const double *B, double *C);

/* Ainv = A^{-1}. Returns 0 on success, -1 if singular. */
int cmat2_invert(const double *A, double *Ainv);

/* det(A) as separate real and imaginary parts */
void cmat2_determinant(const double *A, double *det_re, double *det_im);

/* C = A + B */
void cmat2_add(const double *A, const double *B, double *C);

/* C = A - B */
void cmat2_subtract(const double *A, const double *B, double *C);

/* C = (scale_re + j*scale_im) * A   (element-wise complex scalar multiply) */
void cmat2_scale(const double *A, double scale_re, double scale_im, double *C);

/* I = 2x2 identity matrix */
void cmat2_identity(double *I);

/* D = diag(d00_re+j*d00_im, d11_re+j*d11_im) */
void cmat2_diag(double d00_re, double d00_im, double d11_re, double d11_im, double *D);

#endif

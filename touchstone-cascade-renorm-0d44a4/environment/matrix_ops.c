/*
 * Complex 2x2 matrix operations.
 * See matrix_ops.h for API documentation.
 *
 * Storage: flat double[8] with layout
 *   [re(0,0), im(0,0), re(0,1), im(0,1), re(1,0), im(1,0), re(1,1), im(1,1)]
 */

#include "matrix_ops.h"
#include <string.h>

void cmat2_multiply(const double *A, const double *B, double *C) {
    double a00r = A[0], a00i = A[1], a01r = A[2], a01i = A[3];
    double a10r = A[4], a10i = A[5], a11r = A[6], a11i = A[7];
    double b00r = B[0], b00i = B[1], b01r = B[2], b01i = B[3];
    double b10r = B[4], b10i = B[5], b11r = B[6], b11i = B[7];

    /* C[0,0] = A[0,0]*B[0,0] + A[0,1]*B[1,0] */
    C[0] = (a00r*b00r - a00i*b00i) + (a01r*b10r - a01i*b10i);
    C[1] = (a00r*b00i + a00i*b00r) + (a01r*b10i + a01i*b10r);
    /* C[0,1] = A[0,0]*B[0,1] + A[0,1]*B[1,1] */
    C[2] = (a00r*b01r - a00i*b01i) + (a01r*b11r - a01i*b11i);
    C[3] = (a00r*b01i + a00i*b01r) + (a01r*b11i + a01i*b11r);
    /* C[1,0] = A[1,0]*B[0,0] + A[1,1]*B[1,0] */
    C[4] = (a10r*b00r - a10i*b00i) + (a11r*b10r - a11i*b10i);
    C[5] = (a10r*b00i + a10i*b00r) + (a11r*b10i + a11i*b10r);
    /* C[1,1] = A[1,0]*B[0,1] + A[1,1]*B[1,1] */
    C[6] = (a10r*b01r - a10i*b01i) + (a11r*b11r - a11i*b11i);
    C[7] = (a10r*b01i + a10i*b01r) + (a11r*b11i + a11i*b11r);
}

void cmat2_determinant(const double *A, double *det_re, double *det_im) {
    double a00r = A[0], a00i = A[1], a01r = A[2], a01i = A[3];
    double a10r = A[4], a10i = A[5], a11r = A[6], a11i = A[7];

    /* det = A[0,0]*A[1,1] - A[0,1]*A[1,0] */
    *det_re = (a00r*a11r - a00i*a11i) - (a01r*a10r - a01i*a10i);
    *det_im = (a00r*a11i + a00i*a11r) - (a01r*a10i + a01i*a10r);
}

int cmat2_invert(const double *A, double *Ainv) {
    double det_re, det_im;
    cmat2_determinant(A, &det_re, &det_im);

    double det_mag2 = det_re*det_re + det_im*det_im;
    if (det_mag2 < 1e-30) return -1;

    double inv_re =  det_re / det_mag2;
    double inv_im = -det_im / det_mag2;

    double a00r = A[0], a00i = A[1], a01r = A[2], a01i = A[3];
    double a10r = A[4], a10i = A[5], a11r = A[6], a11i = A[7];

    /* Ainv = (1/det) * [[A11, -A01], [-A10, A00]] */
    Ainv[0] =  a11r*inv_re - a11i*inv_im;
    Ainv[1] =  a11r*inv_im + a11i*inv_re;
    Ainv[2] = -(a01r*inv_re - a01i*inv_im);
    Ainv[3] = -(a01r*inv_im + a01i*inv_re);
    Ainv[4] = -(a10r*inv_re - a10i*inv_im);
    Ainv[5] = -(a10r*inv_im + a10i*inv_re);
    Ainv[6] =  a00r*inv_re - a00i*inv_im;
    Ainv[7] =  a00r*inv_im + a00i*inv_re;

    return 0;
}

void cmat2_add(const double *A, const double *B, double *C) {
    int i;
    for (i = 0; i < 8; i++) C[i] = A[i] + B[i];
}

void cmat2_subtract(const double *A, const double *B, double *C) {
    int i;
    for (i = 0; i < 8; i++) C[i] = A[i] - B[i];
}

void cmat2_scale(const double *A, double sr, double si, double *C) {
    int i;
    for (i = 0; i < 4; i++) {
        double re = A[2*i], im = A[2*i+1];
        C[2*i]   = re*sr - im*si;
        C[2*i+1] = re*si + im*sr;
    }
}

void cmat2_identity(double *I) {
    memset(I, 0, 8 * sizeof(double));
    I[0] = 1.0;
    I[6] = 1.0;
}

void cmat2_diag(double d00_re, double d00_im, double d11_re, double d11_im, double *D) {
    memset(D, 0, 8 * sizeof(double));
    D[0] = d00_re;
    D[1] = d00_im;
    D[6] = d11_re;
    D[7] = d11_im;
}

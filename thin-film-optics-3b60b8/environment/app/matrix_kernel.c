/* Complex 2x2 matrix operations for TMM transfer matrix chain.
 *
 *
 * Memory layout per matrix: 8 doubles (row-major, real/imag interleaved)
 *   [Re(m00), Im(m00), Re(m01), Im(m01), Re(m10), Im(m10), Re(m11), Im(m11)]
 *
 * Functions:
 *   mat2x2_mul(A, B, C)              -- C = A * B
 *   mat2x2_chain_multiply(M, n, out) -- out = M[0] * M[1] * ... * M[n-1]
 *   mat2x2_inv(A, B)                 -- B = A^{-1}
 */

#include <string.h>

void mat2x2_mul(const double *A, const double *B, double *C) {
    double a_re, a_im, b_re, b_im;

    /* C[0,0] = A[0,0]*B[0,0] + A[0,1]*B[1,0] */
    a_re = A[0]*B[0] - A[1]*B[1]; a_im = A[0]*B[1] + A[1]*B[0];
    b_re = A[2]*B[4] - A[3]*B[5]; b_im = A[2]*B[5] + A[3]*B[4];
    C[0] = a_re + b_re; C[1] = a_im + b_im;

    /* C[0,1] = A[0,0]*B[0,1] + A[0,1]*B[1,1] */
    a_re = A[0]*B[2] - A[1]*B[3]; a_im = A[0]*B[3] + A[1]*B[2];
    b_re = A[2]*B[6] - A[3]*B[7]; b_im = A[2]*B[7] + A[3]*B[6];
    C[2] = a_re + b_re; C[3] = a_im + b_im;

    /* C[1,0] = A[1,0]*B[0,0] + A[1,1]*B[1,0] */
    a_re = A[4]*B[0] - A[5]*B[1]; a_im = A[4]*B[1] + A[5]*B[0];
    b_re = A[6]*B[4] - A[7]*B[5]; b_im = A[6]*B[5] + A[7]*B[4];
    C[4] = a_re + b_re; C[5] = a_im + b_im;

    /* C[1,1] = A[1,0]*B[0,1] + A[1,1]*B[1,1] */
    a_re = A[4]*B[2] - A[5]*B[3]; a_im = A[4]*B[3] + A[5]*B[2];
    b_re = A[6]*B[6] - A[7]*B[7]; b_im = A[6]*B[7] + A[7]*B[6];
    C[6] = a_re + b_re; C[7] = a_im + b_im;
}

void mat2x2_chain_multiply(const double *matrices, int n, double *out) {
    double tmp[8];
    /* Initialize to identity */
    memset(out, 0, 8 * sizeof(double));
    out[0] = 1.0;  /* Re(m00) = 1 */
    out[6] = 1.0;  /* Re(m11) = 1 */

    for (int i = 0; i < n; i++) {
        memcpy(tmp, out, 8 * sizeof(double));
        mat2x2_mul(matrices + i * 8, tmp, out);
    }
}

void mat2x2_inv(const double *A, double *B) {
    /* det = A[0,0]*A[1,1] - A[0,1]*A[1,0] */
    double det_re = A[0]*A[6] - A[1]*A[7] - (A[2]*A[4] - A[3]*A[5]);
    double det_im = A[0]*A[7] + A[1]*A[6] - (A[2]*A[5] + A[3]*A[4]);
    double det_mag2 = det_re*det_re + det_im*det_im;
    double inv_re = det_re / det_mag2;
    double inv_im = -det_im / det_mag2;

    /* B = (1/det) * | d  -b |
     *               | -c   a | */
    B[0] = A[6]*inv_re - A[7]*inv_im;
    B[1] = A[6]*inv_im + A[7]*inv_re;
    B[2] = -(A[2]*inv_re - A[3]*inv_im);
    B[3] = -(A[2]*inv_im + A[3]*inv_re);
    B[4] = -(A[4]*inv_re - A[5]*inv_im);
    B[5] = -(A[4]*inv_im + A[5]*inv_re);
    B[6] = A[0]*inv_re - A[1]*inv_im;
    B[7] = A[0]*inv_im + A[1]*inv_re;
}

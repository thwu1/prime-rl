 */

#ifndef EIGENSOLVE_H
#define EIGENSOLVE_H

/*
 * Compute eigenvalues and right eigenvectors of a 4x4 real matrix.
 *
 * Parameters:
 *   A   - Input 4x4 matrix in row-major order (16 doubles)
 *   wr  - Output: real parts of 4 eigenvalues
 *   wi  - Output: imaginary parts of 4 eigenvalues
 *   vr  - Output: right eigenvectors; after the call, the j-th
 *         eigenvector occupies column j of the 4x4 row-major matrix,
 *         i.e. vr[i*4+j] is component i of eigenvector j.
 *
 * Returns: 0 on success, non-zero on failure.
 */
int eig4x4(const double *A, double *wr, double *wi, double *vr);

#endif

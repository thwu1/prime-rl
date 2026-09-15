#ifndef SGWT_NATIVE_H
#define SGWT_NATIVE_H

/* Chebyshev coefficient computation via DCT quadrature.
 * kernel_vals: kernel evaluated at m+1 Chebyshev nodes mapped to [0, lmax]
 * m:          polynomial order
 * coeffs:     output array of m+1 coefficients (pre-allocated by caller)
 */
void compute_cheby_coeff_c(const double *kernel_vals, int m, double *coeffs);

/* Apply Chebyshev polynomial filter to a graph signal using three-term recurrence.
 * L_data, L_indices, L_indptr: CSR sparse matrix components of the graph Laplacian
 * N:       matrix dimension (number of vertices)
 * c_all:   Chebyshev coefficients, shape [Nscales x M] in row-major order
 * Nscales: number of filters in the filterbank
 * M:       number of Chebyshev coefficients per filter
 * signal:  input graph signal of length N
 * lmax:    maximum eigenvalue of the Laplacian
 * result:  output buffer of length N*Nscales, written as result[n*Nscales + s]
 */
void cheby_op_c(const double *L_data, const int *L_indices, const int *L_indptr,
                int N, const double *c_all, int Nscales, int M,
                const double *signal, double lmax, double *result);

#endif

#ifndef SPARSE_OPS_H
#define SPARSE_OPS_H

/* CSR SpMV: y = A*x */
void csr_spmv(int dim, const int *row_ptr, const int *col_idx,
              const double *values, const double *x, double *y);

/* ELLPACK SpMV: y = A*x using ELLPACK arrays */
void ell_spmv(int dim, int max_nnz, const int *ell_col_idx,
              const double *ell_data, const double *x, double *y);

/* Compute matrix bandwidth: max |i - j| over all non-zeros A(i,j) */
int compute_bandwidth(int dim, const int *row_ptr, const int *col_idx);

/* Compute matrix profile: sum of per-row envelopes */
int compute_profile(int dim, const int *row_ptr, const int *col_idx);

#endif

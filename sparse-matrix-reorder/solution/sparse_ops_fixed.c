#include "sparse_ops.h"
#include <stdlib.h>
#include <math.h>

void csr_spmv(int dim, const int *row_ptr, const int *col_idx,
              const double *values, const double *x, double *y)
{
    int i, j;
    for (i = 0; i < dim; i++) {
        y[i] = 0.0;
        for (j = row_ptr[i]; j < row_ptr[i + 1]; j++) {
            y[i] += values[j] * x[col_idx[j]];
        }
    }
}

void ell_spmv(int dim, int max_nnz, const int *ell_col_idx,
              const double *ell_data, const double *x, double *y)
{
    int i, k;
    for (i = 0; i < dim; i++) {
        y[i] = 0.0;
        for (k = 0; k < max_nnz; k++) {
            int idx = i * max_nnz + k;
            int col = ell_col_idx[idx];
            if (col >= 0) {
                y[i] += ell_data[idx] * x[col];
            }
        }
    }
}

int compute_bandwidth(int dim, const int *row_ptr, const int *col_idx)
{
    int bw = 0;
    int i, j;
    for (i = 0; i < dim; i++) {
        for (j = row_ptr[i]; j < row_ptr[i + 1]; j++) {
            int diff = abs(i - col_idx[j]);
            if (diff > bw) bw = diff;
        }
    }
    return bw;
}

int compute_profile(int dim, const int *row_ptr, const int *col_idx)
{
    int profile = 0;
    int i, j;
    for (i = 0; i < dim; i++) {
        if (row_ptr[i] < row_ptr[i + 1]) {
            int min_col = dim;
            for (j = row_ptr[i]; j < row_ptr[i + 1]; j++) {
                if (col_idx[j] < min_col) min_col = col_idx[j];
            }
            int envelope = i - min_col;
            if (envelope > 0) {
                profile += envelope;
            }
        }
    }
    return profile;
}

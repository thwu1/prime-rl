#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "sgwt_native.h"


void compute_cheby_coeff_c(const double *kernel_vals, int m, double *coeffs) {
    int N = m + 1;
    for (int k = 0; k <= m; k++) {
        double sum = 0.0;
        for (int j = 0; j < N; j++) {
            sum += kernel_vals[j] * cos(M_PI * k * (j + 0.5) / N);
        }
        coeffs[k] = (2.0 / N) * sum;
    }
}


void cheby_op_c(const double *L_data, const int *L_indices, const int *L_indptr,
                int N, const double *c_all, int Nscales, int M,
                const double *signal, double lmax, double *result) {
    double a1 = lmax / 2.0;
    double a2 = lmax / 2.0;

    double *twf_old = (double *)calloc(N, sizeof(double));
    double *twf_cur = (double *)calloc(N, sizeof(double));
    double *twf_new = (double *)calloc(N, sizeof(double));

    /* T_0(L') s = s */
    memcpy(twf_old, signal, N * sizeof(double));

    /* T_1(L') s = (L s - a2 s) / a1 */
    for (int i = 0; i < N; i++) {
        double Ls_i = 0.0;
        for (int p = L_indptr[i]; p < L_indptr[i + 1]; p++) {
            Ls_i += L_data[p] * signal[L_indices[p]];
        }
        twf_cur[i] = (Ls_i - a2 * signal[i]) / a1;
    }

    /* Accumulate k=0 and k=1 contributions */
    memset(result, 0, N * Nscales * sizeof(double));
    for (int s = 0; s < Nscales; s++) {
        for (int n = 0; n < N; n++) {
            result[n * Nscales + s] = 0.5 * c_all[s * M + 0] * twf_old[n]
                                     + c_all[s * M + 1] * twf_cur[n];
        }
    }

    /* Three-term recurrence for k >= 2 */
    for (int k = 2; k < M; k++) {
        for (int n = 0; n < N; n++) {
            double Lv = 0.0;
            for (int p = L_indptr[n]; p < L_indptr[n + 1]; p++) {
                Lv += L_data[p] * twf_cur[L_indices[p]];
            }
            twf_new[n] = (2.0 / a1) * (Lv - a2 * twf_cur[n]) + twf_old[n];
        }

        for (int s = 0; s < Nscales; s++) {
            for (int n = 0; n < N; n++) {
                result[n * Nscales + s] += c_all[s * M + k] * twf_new[n];
            }
        }

        memcpy(twf_old, twf_cur, N * sizeof(double));
        memcpy(twf_cur, twf_new, N * sizeof(double));
    }

    free(twf_old);
    free(twf_cur);
    free(twf_new);
}

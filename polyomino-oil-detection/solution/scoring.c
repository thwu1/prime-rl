#include "scoring.h"
#include <math.h>
#include <float.h>

double score_combo(int N, double eps, int num_rounds,
                   const double *row_avg, const double *col_avg,
                   const int *combo_rc, const int *combo_cc) {
    double c_val = 1.0 - 2.0 * eps;
    if (fabs(c_val) < 0.01) c_val = 0.01;
    double sigma_sq = N * eps * (1.0 - eps) / num_rounds;
    if (sigma_sq < 1e-12) sigma_sq = 1e-12;

    double s = 0.0;
    int i;
    for (i = 0; i < N; i++) {
        double mu = N * eps + combo_rc[i] * c_val;
        double d = row_avg[i] - mu;
        s -= d * d;
    }
    for (i = 0; i < N; i++) {
        double mu = N * eps + combo_cc[i] * c_val;
        double d = col_avg[i] - mu;
        s -= d * d;
    }
    return s / (2.0 * sigma_sq);
}

int find_best_combo(int N, double eps, int num_rounds,
                    const double *row_avg, const double *col_avg,
                    const int *combo_rcs, const int *combo_ccs,
                    int num_combos) {
    double best_score = -DBL_MAX;
    int best_idx = 0;
    int c;

    for (c = 0; c < num_combos; c++) {
        double s = score_combo(N, eps, num_rounds,
                               row_avg, col_avg,
                               combo_rcs + c * N,
                               combo_ccs + c * N);
        if (s > best_score) {
            best_score = s;
            best_idx = c;
        }
    }
    return best_idx;
}

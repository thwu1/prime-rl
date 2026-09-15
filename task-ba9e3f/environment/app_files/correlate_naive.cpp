#include "correlate.h"
#include <cmath>

// Naive reference implementation — do not modify.
void correlate(int n, int d, const float* input, float* output) {
    for (int i = 0; i < n; i++) {
        for (int j = i; j < n; j++) {
            // Compute means
            double mean_i = 0.0, mean_j = 0.0;
            for (int k = 0; k < d; k++) {
                mean_i += input[i * d + k];
                mean_j += input[j * d + k];
            }
            mean_i /= d;
            mean_j /= d;

            // Compute correlation components
            double sum_ij = 0.0, sum_ii = 0.0, sum_jj = 0.0;
            for (int k = 0; k < d; k++) {
                double vi = input[i * d + k] - mean_i;
                double vj = input[j * d + k] - mean_j;
                sum_ij += vi * vj;
                sum_ii += vi * vi;
                sum_jj += vj * vj;
            }

            double corr = sum_ij / (std::sqrt(sum_ii) * std::sqrt(sum_jj));
            output[i * n + j] = static_cast<float>(corr);
            output[j * n + i] = static_cast<float>(corr);
        }
    }
}

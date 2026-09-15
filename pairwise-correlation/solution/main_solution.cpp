// Complete solution for weighted pairwise-complete Pearson correlation.
//

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <algorithm>
#include <tuple>

int main(int argc, char* argv[]) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <input.bin> <K> <min_samples> <output.bin>\n", argv[0]);
        return 1;
    }

    const char* input_path = argv[1];
    int K = atoi(argv[2]);
    int min_samples = atoi(argv[3]);
    const char* output_path = argv[4];

    // --- Read binary input ---
    FILE* fin = fopen(input_path, "rb");
    if (!fin) {
        perror("fopen input");
        return 1;
    }

    char magic[4];
    if (fread(magic, 1, 4, fin) != 4 || memcmp(magic, "CORR", 4) != 0) {
        fprintf(stderr, "Invalid magic bytes\n");
        fclose(fin);
        return 1;
    }

    uint32_t n, m;
    if (fread(&n, sizeof(uint32_t), 1, fin) != 1) { fclose(fin); return 1; }
    if (fread(&m, sizeof(uint32_t), 1, fin) != 1) { fclose(fin); return 1; }

    std::vector<double> weights(m);
    if (fread(weights.data(), sizeof(double), m, fin) != m) { fclose(fin); return 1; }

    std::vector<double> data(static_cast<size_t>(n) * m);
    if (fread(data.data(), sizeof(double), static_cast<size_t>(n) * m, fin)
        != static_cast<size_t>(n) * m) { fclose(fin); return 1; }
    fclose(fin);

    // --- Compute correlations ---
    size_t num_pairs = static_cast<size_t>(n) * (n - 1) / 2;
    std::vector<double> corr_matrix(num_pairs, NAN);

    // Collect valid (non-NaN) pairs for top-K
    std::vector<std::tuple<double, uint32_t, uint32_t>> valid_pairs;

    size_t pair_idx = 0;
    for (uint32_t i = 0; i < n; i++) {
        for (uint32_t j = i + 1; j < n; j++) {
            // Find valid columns (neither row has NaN)
            int count = 0;
            for (uint32_t k = 0; k < m; k++) {
                double vi = data[static_cast<size_t>(i) * m + k];
                double vj = data[static_cast<size_t>(j) * m + k];
                if (!std::isnan(vi) && !std::isnan(vj)) {
                    count++;
                }
            }

            if (count < min_samples) {
                corr_matrix[pair_idx] = NAN;
                pair_idx++;
                continue;
            }

            // Compute total weight of valid columns
            double W = 0.0;
            for (uint32_t k = 0; k < m; k++) {
                double vi = data[static_cast<size_t>(i) * m + k];
                double vj = data[static_cast<size_t>(j) * m + k];
                if (!std::isnan(vi) && !std::isnan(vj)) {
                    W += weights[k];
                }
            }

            if (W == 0.0) {
                corr_matrix[pair_idx] = NAN;
                pair_idx++;
                continue;
            }

            // Compute weighted means
            double mu_i = 0.0, mu_j = 0.0;
            for (uint32_t k = 0; k < m; k++) {
                double vi = data[static_cast<size_t>(i) * m + k];
                double vj = data[static_cast<size_t>(j) * m + k];
                if (!std::isnan(vi) && !std::isnan(vj)) {
                    double wn = weights[k] / W;
                    mu_i += wn * vi;
                    mu_j += wn * vj;
                }
            }

            // Compute weighted variances and covariance
            double var_i = 0.0, var_j = 0.0, cov_ij = 0.0;
            for (uint32_t k = 0; k < m; k++) {
                double vi = data[static_cast<size_t>(i) * m + k];
                double vj = data[static_cast<size_t>(j) * m + k];
                if (!std::isnan(vi) && !std::isnan(vj)) {
                    double wn = weights[k] / W;
                    double di = vi - mu_i;
                    double dj = vj - mu_j;
                    var_i += wn * di * di;
                    var_j += wn * dj * dj;
                    cov_ij += wn * di * dj;
                }
            }

            // Use threshold instead of exact zero comparison to handle
            // floating-point imprecision for constant rows
            if (var_i < 1e-20 || var_j < 1e-20) {
                corr_matrix[pair_idx] = NAN;
                pair_idx++;
                continue;
            }

            double r = cov_ij / (std::sqrt(var_i) * std::sqrt(var_j));
            corr_matrix[pair_idx] = r;

            valid_pairs.emplace_back(r, i, j);
            pair_idx++;
        }
    }

    // --- Sort and output top-K ---
    // Use integer rounding for r comparison to avoid floating-point noise
    // affecting sort order when correlations are nearly equal.
    std::sort(valid_pairs.begin(), valid_pairs.end(),
              [](const auto& a, const auto& b) {
                  long long ra = std::llround(std::get<0>(a) * 1e12);
                  long long rb = std::llround(std::get<0>(b) * 1e12);
                  if (ra != rb) return ra > rb;
                  uint32_t ia = std::get<1>(a), ib = std::get<1>(b);
                  if (ia != ib) return ia < ib;
                  return std::get<2>(a) < std::get<2>(b);
              });

    int output_count = std::min(K, static_cast<int>(valid_pairs.size()));
    for (int idx = 0; idx < output_count; idx++) {
        printf("%u %u %.12f\n",
               std::get<1>(valid_pairs[idx]),
               std::get<2>(valid_pairs[idx]),
               std::get<0>(valid_pairs[idx]));
    }

    // --- Write binary output (RMAT) ---
    FILE* fout = fopen(output_path, "wb");
    if (!fout) {
        perror("fopen output");
        return 1;
    }
    fwrite("RMAT", 1, 4, fout);
    fwrite(&n, sizeof(uint32_t), 1, fout);
    fwrite(corr_matrix.data(), sizeof(double), num_pairs, fout);
    fclose(fout);

    return 0;
}

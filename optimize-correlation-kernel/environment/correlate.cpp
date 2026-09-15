#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

int main() {
    FILE* fin = fopen("/app/input.bin", "rb");
    if (!fin) {
        fprintf(stderr, "Error: cannot open /app/input.bin\n");
        return 1;
    }

    int n, m;
    fread(&n, sizeof(int), 1, fin);
    fread(&m, sizeof(int), 1, fin);

    std::vector<double> data((size_t)n * m);
    fread(data.data(), sizeof(double), (size_t)n * m, fin);
    fclose(fin);

    int num_pairs = n * (n - 1) / 2;
    std::vector<double> result(num_pairs);

    int idx = 0;
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            // Compute means
            double mean_i = 0, mean_j = 0;
            for (int k = 0; k < m; k++) {
                mean_i += data[(size_t)i * m + k];
                mean_j += data[(size_t)j * m + k];
            }
            mean_i /= m;
            mean_j /= m;

            // Compute covariance and variances
            double cov = 0, var_i = 0, var_j = 0;
            for (int k = 0; k < m; k++) {
                double di = data[(size_t)i * m + k] - mean_i;
                double dj = data[(size_t)j * m + k] - mean_j;
                cov += di * dj;
                var_i += di * di;
                var_j += dj * dj;
            }

            double denom = sqrt(var_i * var_j);
            result[idx++] = (denom > 0) ? cov / denom : 0.0;
        }
    }

    FILE* fout = fopen("/app/output.bin", "wb");
    fwrite(&n, sizeof(int), 1, fout);
    fwrite(&num_pairs, sizeof(int), 1, fout);
    fwrite(result.data(), sizeof(double), num_pairs, fout);
    fclose(fout);

    return 0;
}

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <algorithm>

int main() {
    // Read input
    FILE* fin = fopen("/app/input.bin", "rb");
    if (!fin) { fprintf(stderr, "Error: cannot open input\n"); return 1; }
    int n, m;
    fread(&n, sizeof(int), 1, fin);
    fread(&m, sizeof(int), 1, fin);
    std::vector<double> raw((size_t)n * m);
    fread(raw.data(), sizeof(double), (size_t)n * m, fin);
    fclose(fin);

    // Pad columns to multiple of 8 for AVX2 alignment (8 floats per register)
    const int ALIGN = 8;
    int mp = (m + ALIGN - 1) / ALIGN * ALIGN;

    // Key optimization 1: Pre-normalize rows
    // Subtract mean and divide by L2 norm so that
    // Pearson correlation(row_i, row_j) = dot(normalized_i, normalized_j)
    // This eliminates redundant per-pair mean/variance computation.
    //
    // Key optimization 2: Convert to float32
    // Doubles SIMD throughput (8 floats vs 4 doubles per AVX2 register).
    std::vector<float> norm((size_t)n * mp, 0.0f);

    for (int i = 0; i < n; i++) {
        // Compute mean in double precision
        double sum = 0.0;
        for (int k = 0; k < m; k++) {
            sum += raw[(size_t)i * m + k];
        }
        double mean = sum / m;

        // Center the row and compute squared norm
        double sq = 0.0;
        for (int k = 0; k < m; k++) {
            double v = raw[(size_t)i * m + k] - mean;
            norm[(size_t)i * mp + k] = static_cast<float>(v);
            sq += v * v;
        }

        // Normalize to unit L2 norm
        if (sq > 0.0) {
            float inv = static_cast<float>(1.0 / std::sqrt(sq));
            for (int k = 0; k < mp; k++) {
                norm[(size_t)i * mp + k] *= inv;
            }
        }
    }
    // Free raw data - no longer needed
    raw.clear();
    raw.shrink_to_fit();

    // Compute all pairwise correlations as dot products
    long long num_pairs = (long long)n * (n - 1) / 2;
    std::vector<double> result(num_pairs);

    for (int i = 0; i < n; i++) {
        const float* __restrict__ ri = &norm[(size_t)i * mp];
        for (int j = i + 1; j < n; j++) {
            const float* __restrict__ rj = &norm[(size_t)j * mp];

            // Key optimization 3: Multiple independent accumulators
            // Breaks the loop-carried dependency chain on the sum accumulator,
            // allowing the CPU to pipeline FMA operations and enabling the
            // compiler to auto-vectorize even without -ffast-math.
            float d0 = 0, d1 = 0, d2 = 0, d3 = 0;
            float d4 = 0, d5 = 0, d6 = 0, d7 = 0;
            for (int k = 0; k < mp; k += 8) {
                d0 += ri[k]     * rj[k];
                d1 += ri[k + 1] * rj[k + 1];
                d2 += ri[k + 2] * rj[k + 2];
                d3 += ri[k + 3] * rj[k + 3];
                d4 += ri[k + 4] * rj[k + 4];
                d5 += ri[k + 5] * rj[k + 5];
                d6 += ri[k + 6] * rj[k + 6];
                d7 += ri[k + 7] * rj[k + 7];
            }
            float dot = (d0 + d1) + (d2 + d3) + (d4 + d5) + (d6 + d7);

            long long idx = (long long)(2 * n - i - 1) * i / 2 + (j - i - 1);
            result[idx] = static_cast<double>(dot);
        }
    }

    // Write output
    FILE* fout = fopen("/app/output.bin", "wb");
    int np_out = static_cast<int>(num_pairs);
    fwrite(&n, sizeof(int), 1, fout);
    fwrite(&np_out, sizeof(int), 1, fout);
    fwrite(result.data(), sizeof(double), num_pairs, fout);
    fclose(fout);

    return 0;
}

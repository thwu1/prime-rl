
// Optimized Pearson correlation kernel.
//
// Key optimizations:
// 1. Pre-normalize all rows: subtract mean, divide by L2 norm of centered row.
//    After this, Pearson correlation = dot product. This eliminates O(n^2 d)
//    redundant mean/variance recomputation (the naive version recomputes the
//    mean of row i for every pair involving i).
// 2. Use float throughout instead of double — doubles SIMD throughput on the
//    same vector width (SSE: 4 floats vs 2 doubles; AVX: 8 vs 4).
// 3. Pragma fast-math to enable auto-vectorization of reduction (dot product)
//    loops, which the compiler cannot do under strict IEEE-754 semantics.
// 4. Pad rows to a SIMD-friendly width and use aligned allocation so the
//    compiler can emit aligned vector loads.
// 5. Cache-block the outer pair loops so that rows being dotted remain in L1/L2.

#pragma GCC optimize("O3,fast-math,unroll-loops")

#include "correlate.h"
#include <cmath>
#include <cstdlib>
#include <cstring>

void correlate(int n, int d, const float* input, float* output) {
    // Pad dimension to next multiple of 16 for SIMD alignment
    const int dp = (d + 15) & ~15;

    // Allocate aligned, zero-padded normalized data
    const size_t data_bytes = static_cast<size_t>(n) * dp * sizeof(float);
    float* __restrict__ norm = static_cast<float*>(aligned_alloc(64, data_bytes));
    std::memset(norm, 0, data_bytes);

    // --- Step 1: Pre-normalize all rows ---
    for (int i = 0; i < n; i++) {
        float* __restrict__ row = norm + static_cast<size_t>(i) * dp;

        // Compute mean
        float sum = 0.0f;
        for (int k = 0; k < d; k++) {
            sum += input[static_cast<size_t>(i) * d + k];
        }
        const float mean = sum / static_cast<float>(d);

        // Center and compute squared L2 norm
        float sq_sum = 0.0f;
        for (int k = 0; k < d; k++) {
            float v = input[static_cast<size_t>(i) * d + k] - mean;
            row[k] = v;
            sq_sum += v * v;
        }

        // Scale to unit L2 norm
        const float inv_norm = 1.0f / std::sqrt(sq_sum);
        for (int k = 0; k < d; k++) {
            row[k] *= inv_norm;
        }
    }

    // --- Step 2: Correlation = dot product of normalized rows ---
    // Cache-blocked pairwise dot products.
    const int BLOCK = 64;

    for (int i0 = 0; i0 < n; i0 += BLOCK) {
        const int i1 = (i0 + BLOCK < n) ? i0 + BLOCK : n;
        for (int j0 = i0; j0 < n; j0 += BLOCK) {
            const int j1 = (j0 + BLOCK < n) ? j0 + BLOCK : n;
            for (int i = i0; i < i1; i++) {
                const float* __restrict__ ri = norm + static_cast<size_t>(i) * dp;
                const int js = (j0 > i) ? j0 : i;
                for (int j = js; j < j1; j++) {
                    const float* __restrict__ rj = norm + static_cast<size_t>(j) * dp;
                    float dot = 0.0f;
                    for (int k = 0; k < dp; k++) {
                        dot += ri[k] * rj[k];
                    }
                    output[static_cast<size_t>(i) * n + j] = dot;
                    output[static_cast<size_t>(j) * n + i] = dot;
                }
            }
        }
    }

    std::free(norm);
}

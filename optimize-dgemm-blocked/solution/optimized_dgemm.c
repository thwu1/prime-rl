
const char* dgemm_desc = "Optimized blocked dgemm with copy optimization";

#include <string.h>

/*
 * Block size chosen so that two packed panels (each BS*BS*8 bytes = ~18 KB)
 * fit comfortably in L1 data cache (typically 32-48 KB), leaving room for
 * the C sub-block being updated.
 */
#define BS 48
#define min(a, b) (((a) < (b)) ? (a) : (b))

/*
 * Statically-allocated, cache-line-aligned buffers for packed sub-matrices.
 * Using static storage avoids malloc overhead on every block iteration.
 */
static double pA[BS * BS] __attribute__((aligned(64)));
static double pB[BS * BS] __attribute__((aligned(64)));

/*
 * Pack a sub-matrix of A (M rows x K columns, column-major with stride lda)
 * into pA in column-major layout with stride M (contiguous columns of M elements).
 * This converts strided memory access into sequential access, eliminating
 * TLB and cache-line splitting issues for non-power-of-2 leading dimensions.
 */
static inline void pack_panel_A(int lda, int M, int K,
                                const double* restrict A) {
    for (int k = 0; k < K; k++) {
        memcpy(pA + k * M, A + k * lda, (unsigned long)M * sizeof(double));
    }
}

/*
 * Pack a sub-matrix of B (K rows x N columns, column-major with stride lda)
 * into pB in column-major layout with stride K.
 */
static inline void pack_panel_B(int lda, int K, int N,
                                const double* restrict B) {
    for (int j = 0; j < N; j++) {
        memcpy(pB + j * K, B + j * lda, (unsigned long)K * sizeof(double));
    }
}

/*
 * Micro-kernel: compute C(M x N) += pA(M x K) * pB(K x N).
 *
 * Loop ordering is j-k-i:
 *   - Outer j: iterate over columns of C/B
 *   - Middle k: accumulate products
 *   - Inner i: vectorizable sequential sweep over rows of A and C
 *
 * The scalar b_kj is hoisted out of the inner loop, and the inner i-loop
 * accesses pA[i + k*M] and C[i + j*lda] sequentially, enabling the compiler
 * to auto-vectorize with SIMD instructions (SSE2/AVX2).
 */
static void kernel_multiply(int M, int N, int K, int lda,
                            double* restrict C) {
    for (int j = 0; j < N; j++) {
        double* restrict cj = C + j * lda;
        for (int k = 0; k < K; k++) {
            double b_kj = pB[k + j * K];
            const double* restrict ak = pA + k * M;
            for (int i = 0; i < M; i++) {
                cj[i] += ak[i] * b_kj;
            }
        }
    }
}

/*
 * Top-level DGEMM: C := C + A * B
 * A, B, C are lda-by-lda column-major matrices.
 *
 * Outer block ordering is j-k-i (GEBP variant):
 *   - j loop: select a panel of columns from B and C
 *   - k loop: select a panel of rows from A and columns from B;
 *             pack the B sub-panel once and reuse it across all i-blocks
 *   - i loop: select a panel of rows from A and C;
 *             pack the A sub-panel and multiply against the already-packed B
 *
 * This ordering maximises reuse of pB across multiple i-blocks,
 * keeping pB warm in L2 cache while pA cycles through L1.
 */
void square_dgemm(int lda, double* A, double* B, double* C) {
    for (int j = 0; j < lda; j += BS) {
        int N = min(BS, lda - j);
        for (int k = 0; k < lda; k += BS) {
            int K = min(BS, lda - k);
            /* Pack B sub-panel once for all i-blocks */
            pack_panel_B(lda, K, N, B + k + j * lda);
            for (int i = 0; i < lda; i += BS) {
                int M = min(BS, lda - i);
                /* Pack A sub-panel */
                pack_panel_A(lda, M, K, A + i + k * lda);
                /* Accumulate into C sub-block */
                kernel_multiply(M, N, K, lda, C + i + j * lda);
            }
        }
    }
}

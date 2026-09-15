/*
 *
 * High-performance SGEMM using AVX2/FMA3 intrinsics with BLIS-style cache blocking.
 *
 * Computes C[M x N] = A[M x K] * B[K x N], column-major layout.
 */

#include <immintrin.h>
#include <string.h>
#include "matmul.h"

/* Micro-kernel tile size: 16 rows x 6 columns */
#define MR 16
#define NR 6

/* Cache-blocking tile sizes */
#define MC 640   /* must be multiple of MR */
#define NC 252   /* must be multiple of NR */
#define KC 500

#define MIN(x, y) ((x) < (y) ? (x) : (y))

/* Packed buffers for cache-blocked sub-matrices */
static float blockA_packed[MC * KC] __attribute__((aligned(64)));
static float blockB_packed[NC * KC] __attribute__((aligned(64)));

/*
 * Mask lookup table for partial-tile masked loads/stores.
 * First 16 bytes are -1 (0xFF), next 16 are 0.
 * For mr rows, load 8 bytes starting at offset (16 - mr) to get the
 * correct mask for the lower YMM register, and at (24 - mr) for upper.
 * _mm256_cvtepi8_epi32 sign-extends each byte to int32: -1 -> 0xFFFFFFFF
 * (store), 0 -> 0x00000000 (skip).
 */
static const int8_t mask_lut[32] __attribute__((aligned(64))) = {
    -1, -1, -1, -1, -1, -1, -1, -1,   /* bytes 0-7   */
    -1, -1, -1, -1, -1, -1, -1, -1,   /* bytes 8-15  */
     0,  0,  0,  0,  0,  0,  0,  0,   /* bytes 16-23 */
     0,  0,  0,  0,  0,  0,  0,  0    /* bytes 24-31 */
};

/* -----------------------------------------------------------------------
 * Packing routines
 * -----------------------------------------------------------------------
 * pack_panelA: copy an mr x kc sub-matrix of A (column-major, lda)
 *   into column-contiguous format padded to MR rows.
 *   Layout: packed[p * MR + i] = A[p * lda + i], padded with 0 for i >= mr.
 *
 * pack_panelB: copy a kc x nr sub-matrix of B (column-major, ldb)
 *   into row-contiguous format padded to NR columns.
 *   Layout: packed[p * NR + j] = B[j * ldb + p], padded with 0 for j >= nr.
 */

static void pack_panelA(const float* A, float* packed, int mr, int kc, int lda) {
    for (int p = 0; p < kc; p++) {
        int i = 0;
        for (; i < mr; i++)
            packed[p * MR + i] = A[p * lda + i];
        for (; i < MR; i++)
            packed[p * MR + i] = 0.0f;
    }
}

static void pack_blockA(const float* A, float* packed, int mc, int kc, int lda) {
    for (int i = 0; i < mc; i += MR) {
        int mr = MIN(MR, mc - i);
        pack_panelA(&A[i], &packed[i * kc], mr, kc, lda);
    }
}

static void pack_panelB(const float* B, float* packed, int nr, int kc, int ldb) {
    for (int p = 0; p < kc; p++) {
        int j = 0;
        for (; j < nr; j++)
            packed[p * NR + j] = B[j * ldb + p];
        for (; j < NR; j++)
            packed[p * NR + j] = 0.0f;
    }
}

static void pack_blockB(const float* B, float* packed, int nc, int kc, int ldb) {
    for (int j = 0; j < nc; j += NR) {
        int nr = MIN(NR, nc - j);
        pack_panelB(&B[j * ldb], &packed[j * kc], nr, kc, ldb);
    }
}

/* -----------------------------------------------------------------------
 * 16 x 6 micro-kernel
 * -----------------------------------------------------------------------
 * Computes a 16-row x 6-col sub-block of C using rank-1 outer-product
 * updates: for each of kc iterations, load a 16-element column from
 * packed A and broadcast 6 scalars from packed B, performing 12 FMA
 * operations into 12 YMM accumulator registers.
 *
 * A is packed in column-panel format: column p at A[p*MR].
 * B is packed in row-panel format:   row p at B[p*NR].
 * C is in original column-major format with leading dimension ldc.
 *
 * mr, nr: actual tile dimensions (may be < MR, NR at matrix edges).
 * zero_init: if true, accumulators start at zero; otherwise load from C.
 */
static void kernel_16x6(const float* restrict A, const float* restrict B,
                         float* restrict C, int mr, int nr, int kc, int ldc,
                         int zero_init) {
    /* 12 accumulator registers: 6 columns x 2 YMM per column (16 rows) */
    __m256 C00, C10, C01, C11, C02, C12;
    __m256 C03, C13, C04, C14, C05, C15;
    __m256 a0, a1, b;

    /* Compute masks for partial-tile loads/stores */
    __m256i m0 = _mm256_cvtepi8_epi32(
        _mm_loadl_epi64((const __m128i*)&mask_lut[16 - mr]));
    __m256i m1 = _mm256_cvtepi8_epi32(
        _mm_loadl_epi64((const __m128i*)&mask_lut[24 - mr]));

    /* Initialize accumulators */
    if (zero_init) {
        C00 = _mm256_setzero_ps(); C10 = _mm256_setzero_ps();
        C01 = _mm256_setzero_ps(); C11 = _mm256_setzero_ps();
        C02 = _mm256_setzero_ps(); C12 = _mm256_setzero_ps();
        C03 = _mm256_setzero_ps(); C13 = _mm256_setzero_ps();
        C04 = _mm256_setzero_ps(); C14 = _mm256_setzero_ps();
        C05 = _mm256_setzero_ps(); C15 = _mm256_setzero_ps();
    } else {
        /* Load partial C using masked loads to avoid out-of-bounds reads */
        C00 = (nr > 0) ? _mm256_maskload_ps(&C[0 * ldc],     m0) : _mm256_setzero_ps();
        C10 = (nr > 0) ? _mm256_maskload_ps(&C[0 * ldc + 8], m1) : _mm256_setzero_ps();
        C01 = (nr > 1) ? _mm256_maskload_ps(&C[1 * ldc],     m0) : _mm256_setzero_ps();
        C11 = (nr > 1) ? _mm256_maskload_ps(&C[1 * ldc + 8], m1) : _mm256_setzero_ps();
        C02 = (nr > 2) ? _mm256_maskload_ps(&C[2 * ldc],     m0) : _mm256_setzero_ps();
        C12 = (nr > 2) ? _mm256_maskload_ps(&C[2 * ldc + 8], m1) : _mm256_setzero_ps();
        C03 = (nr > 3) ? _mm256_maskload_ps(&C[3 * ldc],     m0) : _mm256_setzero_ps();
        C13 = (nr > 3) ? _mm256_maskload_ps(&C[3 * ldc + 8], m1) : _mm256_setzero_ps();
        C04 = (nr > 4) ? _mm256_maskload_ps(&C[4 * ldc],     m0) : _mm256_setzero_ps();
        C14 = (nr > 4) ? _mm256_maskload_ps(&C[4 * ldc + 8], m1) : _mm256_setzero_ps();
        C05 = (nr > 5) ? _mm256_maskload_ps(&C[5 * ldc],     m0) : _mm256_setzero_ps();
        C15 = (nr > 5) ? _mm256_maskload_ps(&C[5 * ldc + 8], m1) : _mm256_setzero_ps();
    }

    /* Rank-1 update loop: accumulate kc outer products */
    for (int p = 0; p < kc; p++) {
        /* Load 16-element column from packed A */
        a0 = _mm256_loadu_ps(&A[p * MR]);
        a1 = _mm256_loadu_ps(&A[p * MR + 8]);

        /* Column 0: broadcast B[p,0], FMA into accumulators */
        b = _mm256_broadcast_ss(&B[p * NR + 0]);
        C00 = _mm256_fmadd_ps(a0, b, C00);
        C10 = _mm256_fmadd_ps(a1, b, C10);

        /* Column 1 */
        b = _mm256_broadcast_ss(&B[p * NR + 1]);
        C01 = _mm256_fmadd_ps(a0, b, C01);
        C11 = _mm256_fmadd_ps(a1, b, C11);

        /* Column 2 */
        b = _mm256_broadcast_ss(&B[p * NR + 2]);
        C02 = _mm256_fmadd_ps(a0, b, C02);
        C12 = _mm256_fmadd_ps(a1, b, C12);

        /* Column 3 */
        b = _mm256_broadcast_ss(&B[p * NR + 3]);
        C03 = _mm256_fmadd_ps(a0, b, C03);
        C13 = _mm256_fmadd_ps(a1, b, C13);

        /* Column 4 */
        b = _mm256_broadcast_ss(&B[p * NR + 4]);
        C04 = _mm256_fmadd_ps(a0, b, C04);
        C14 = _mm256_fmadd_ps(a1, b, C14);

        /* Column 5 */
        b = _mm256_broadcast_ss(&B[p * NR + 5]);
        C05 = _mm256_fmadd_ps(a0, b, C05);
        C15 = _mm256_fmadd_ps(a1, b, C15);
    }

    /* Store accumulators to C with masked stores for edge tiles */
    if (nr > 0) { _mm256_maskstore_ps(&C[0 * ldc],     m0, C00);
                   _mm256_maskstore_ps(&C[0 * ldc + 8], m1, C10); }
    if (nr > 1) { _mm256_maskstore_ps(&C[1 * ldc],     m0, C01);
                   _mm256_maskstore_ps(&C[1 * ldc + 8], m1, C11); }
    if (nr > 2) { _mm256_maskstore_ps(&C[2 * ldc],     m0, C02);
                   _mm256_maskstore_ps(&C[2 * ldc + 8], m1, C12); }
    if (nr > 3) { _mm256_maskstore_ps(&C[3 * ldc],     m0, C03);
                   _mm256_maskstore_ps(&C[3 * ldc + 8], m1, C13); }
    if (nr > 4) { _mm256_maskstore_ps(&C[4 * ldc],     m0, C04);
                   _mm256_maskstore_ps(&C[4 * ldc + 8], m1, C14); }
    if (nr > 5) { _mm256_maskstore_ps(&C[5 * ldc],     m0, C05);
                   _mm256_maskstore_ps(&C[5 * ldc + 8], m1, C15); }
}

/* -----------------------------------------------------------------------
 * Top-level SGEMM with 5-loop BLIS cache blocking
 * -----------------------------------------------------------------------
 * Loop nest (outermost to innermost):
 *   Loop 5 (j):  N dimension in steps of NC  -> B panel in L3
 *   Loop 4 (p):  K dimension in steps of KC  -> pack B
 *   Loop 3 (i):  M dimension in steps of MC  -> A panel in L2, pack A
 *   Loop 2 (jr): NC dimension in steps of NR -> micro-panel of B
 *   Loop 1 (ir): MC dimension in steps of MR -> micro-panel of A -> kernel
 */
void matmul(float* A, float* B, float* C, int M, int N, int K) {
    for (int j = 0; j < N; j += NC) {
        int nc = MIN(NC, N - j);
        for (int p = 0; p < K; p += KC) {
            int kc = MIN(KC, K - p);

            /* Pack kc x nc block of B into row-panel format */
            pack_blockB(&B[j * K + p], blockB_packed, nc, kc, K);

            for (int i = 0; i < M; i += MC) {
                int mc = MIN(MC, M - i);

                /* Pack mc x kc block of A into column-panel format */
                pack_blockA(&A[p * M + i], blockA_packed, mc, kc, M);

                /* Dispatch micro-kernel calls over packed panels */
                for (int jr = 0; jr < nc; jr += NR) {
                    int nr = MIN(NR, nc - jr);
                    for (int ir = 0; ir < mc; ir += MR) {
                        int mr = MIN(MR, mc - ir);
                        kernel_16x6(
                            &blockA_packed[ir * kc],
                            &blockB_packed[jr * kc],
                            &C[(j + jr) * M + (i + ir)],
                            mr, nr, kc, M,
                            /* zero_init on first K-tile, accumulate after */
                            p == 0
                        );
                    }
                }
            }
        }
    }
}

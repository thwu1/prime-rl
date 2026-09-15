/* qmatmul_solution.c — Complete implementation including adaptive_quantized_matmul */


#include "qmatmul.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

int quantize_symmetric(const float *src, int rows, int cols, int src_stride,
                       int8_t *dst, float *scale) {
    if (!src || !dst || !scale || rows <= 0 || cols <= 0 || src_stride < cols)
        return -1;

    float absmax = 0.0f;
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            float v = fabsf(src[i * src_stride + j]);
            if (v > absmax) absmax = v;
        }
    }

    *scale = (absmax > 0.0f) ? (absmax / 127.0f) : 1.0f;
    float inv_scale = 1.0f / *scale;

    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            int v = (int)roundf(src[i * src_stride + j] * inv_scale);
            if (v < -128) v = -128;
            if (v > 127)  v = 127;
            dst[i * cols + j] = (int8_t)v;
        }
    }

    return 0;
}

int dequantize_symmetric(const int8_t *src, int rows, int cols,
                         float scale, float *dst, int dst_stride) {
    if (!src || !dst || rows <= 0 || cols <= 0 || dst_stride < cols)
        return -1;

    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            dst[i * dst_stride + j] = (float)src[i * cols + j] * scale;
        }
    }

    return 0;
}

int quantize_asymmetric(const float *src, int rows, int cols, int src_stride,
                        int8_t *dst, float *scale, float *zero_point) {
    if (!src || !dst || !scale || !zero_point ||
        rows <= 0 || cols <= 0 || src_stride < cols)
        return -1;

    float x_min = src[0], x_max = src[0];
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            float val = src[i * src_stride + j];
            if (val < x_min) x_min = val;
            if (val > x_max) x_max = val;
        }
    }

    if (x_min == x_max) {
        *scale = 1.0f;
        *zero_point = x_min;
        memset(dst, 0, (size_t)rows * cols * sizeof(int8_t));
        return 0;
    }

    *scale = (x_max - x_min) / 254.0f;
    *zero_point = (x_max + x_min) / 2.0f;
    float inv_scale = 1.0f / *scale;

    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            int v = (int)roundf((src[i * src_stride + j] - *zero_point) * inv_scale);
            if (v < -127) v = -127;
            if (v > 127)  v = 127;
            dst[i * cols + j] = (int8_t)v;
        }
    }

    return 0;
}

int dequantize_asymmetric(const int8_t *src, int rows, int cols,
                          float scale, float zero_point,
                          float *dst, int dst_stride) {
    if (!src || !dst || rows <= 0 || cols <= 0 || dst_stride < cols)
        return -1;

    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            dst[i * dst_stride + j] = (float)src[i * cols + j] * scale + zero_point;
        }
    }

    return 0;
}

int quantized_matmul(const float *A, int M, int K,
                     const float *B, int N,
                     float *C, int block_size, int mode) {
    if (!A || !B || !C || M <= 0 || K <= 0 || N <= 0 || block_size <= 0)
        return -1;
    if (mode != 0 && mode != 1)
        return -1;

    memset(C, 0, (size_t)M * N * sizeof(float));

    int8_t *qa  = (int8_t *)malloc((size_t)block_size * block_size * sizeof(int8_t));
    int8_t *qb  = (int8_t *)malloc((size_t)block_size * block_size * sizeof(int8_t));
    int32_t *row_sums = NULL;
    int32_t *col_sums = NULL;

    if (mode == 1) {
        row_sums = (int32_t *)malloc((size_t)block_size * sizeof(int32_t));
        col_sums = (int32_t *)malloc((size_t)block_size * sizeof(int32_t));
        if (!row_sums || !col_sums) {
            free(qa); free(qb); free(row_sums); free(col_sums);
            return -1;
        }
    }

    if (!qa || !qb) {
        free(qa); free(qb); free(row_sums); free(col_sums);
        return -1;
    }

    for (int kt = 0; kt < K; kt += block_size) {
        int bk = block_size;
        if (kt + bk > K) bk = K - kt;

        for (int mt = 0; mt < M; mt += block_size) {
            int bm = block_size;
            if (mt + bm > M) bm = M - mt;

            float sa, zpa = 0.0f;
            if (mode == 0) {
                quantize_symmetric(A + mt * K + kt, bm, bk, K, qa, &sa);
            } else {
                quantize_asymmetric(A + mt * K + kt, bm, bk, K, qa, &sa, &zpa);

                for (int i = 0; i < bm; i++) {
                    int32_t s = 0;
                    for (int kk = 0; kk < bk; kk++) {
                        s += (int32_t)qa[i * bk + kk];
                    }
                    row_sums[i] = s;
                }
            }

            for (int nt = 0; nt < N; nt += block_size) {
                int bn = block_size;
                if (nt + bn > N) bn = N - nt;

                float sb, zpb = 0.0f;
                if (mode == 0) {
                    quantize_symmetric(B + kt * N + nt, bk, bn, N, qb, &sb);
                } else {
                    quantize_asymmetric(B + kt * N + nt, bk, bn, N, qb, &sb, &zpb);

                    for (int j = 0; j < bn; j++) {
                        int32_t s = 0;
                        for (int kk = 0; kk < bk; kk++) {
                            s += (int32_t)qb[kk * bn + j];
                        }
                        col_sums[j] = s;
                    }
                }

                float sa_sb = sa * sb;

                for (int i = 0; i < bm; i++) {
                    for (int j = 0; j < bn; j++) {
                        int32_t acc = 0;
                        for (int kk = 0; kk < bk; kk++) {
                            acc += (int32_t)qa[i * bk + kk] *
                                   (int32_t)qb[kk * bn + j];
                        }

                        float result = sa_sb * (float)acc;

                        if (mode == 1) {
                            result += sa * zpb * (float)row_sums[i];
                            result += zpa * sb * (float)col_sums[j];
                            result += (float)bk * zpa * zpb;
                        }

                        C[(mt + i) * N + (nt + j)] += result;
                    }
                }
            }
        }
    }

    free(qa);
    free(qb);
    free(row_sums);
    free(col_sums);

    return 0;
}

/*
 * Mode selection heuristic: compare how much of the symmetric INT8 codebook
 * the tile's actual value range uses. Symmetric maps [-absmax, absmax] (full
 * range = 2*absmax). If the tile's actual range [min, max] is much smaller
 * than 2*absmax, symmetric wastes codebook entries; asymmetric is better.
 *
 * utilization = (max - min) / (2 * absmax)
 *   - Near 1.0: data nearly fills symmetric range → symmetric is fine
 *   - Below threshold: data is biased → asymmetric gives finer precision
 */
static int select_tile_mode(const float *src, int rows, int cols, int src_stride) {
    float x_min = src[0], x_max = src[0];
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < cols; j++) {
            float v = src[i * src_stride + j];
            if (v < x_min) x_min = v;
            if (v > x_max) x_max = v;
        }
    }

    float abs_min = fabsf(x_min);
    float abs_max = fabsf(x_max);
    float absmax = (abs_min > abs_max) ? abs_min : abs_max;

    if (absmax == 0.0f) return 0;  /* all zeros: symmetric is fine */

    float range = x_max - x_min;
    float utilization = range / (2.0f * absmax);

    /* If less than 75% of the symmetric range is utilized, asymmetric
       achieves finer quantization precision */
    return (utilization < 0.75f) ? 1 : 0;
}

int adaptive_quantized_matmul(const float *A, int M, int K,
                              const float *B, int N,
                              float *C, int block_size,
                              int *stats) {
    if (!A || !B || !C || M <= 0 || K <= 0 || N <= 0 || block_size <= 0)
        return -1;

    memset(C, 0, (size_t)M * N * sizeof(float));

    /* Allocate buffers for the largest possible tile */
    int8_t  *qa = (int8_t  *)malloc((size_t)block_size * block_size * sizeof(int8_t));
    int8_t  *qb = (int8_t  *)malloc((size_t)block_size * block_size * sizeof(int8_t));
    int32_t *row_sums = (int32_t *)malloc((size_t)block_size * sizeof(int32_t));
    int32_t *col_sums = (int32_t *)malloc((size_t)block_size * sizeof(int32_t));

    if (!qa || !qb || !row_sums || !col_sums) {
        free(qa); free(qb); free(row_sums); free(col_sums);
        return -1;
    }

    int sym_count = 0, asym_count = 0;

    for (int kt = 0; kt < K; kt += block_size) {
        int bk = block_size;
        if (kt + bk > K) bk = K - kt;

        for (int mt = 0; mt < M; mt += block_size) {
            int bm = block_size;
            if (mt + bm > M) bm = M - mt;

            /* Select mode for A-tile and quantize */
            int mode_a = select_tile_mode(A + mt * K + kt, bm, bk, K);
            float sa, zpa = 0.0f;

            if (mode_a == 0) {
                quantize_symmetric(A + mt * K + kt, bm, bk, K, qa, &sa);
                sym_count++;
            } else {
                quantize_asymmetric(A + mt * K + kt, bm, bk, K, qa, &sa, &zpa);
                asym_count++;
            }

            /* Always compute row sums of qa — needed whenever B-tile uses
               asymmetric mode (zpb != 0), which we don't know yet */
            for (int i = 0; i < bm; i++) {
                int32_t s = 0;
                for (int kk = 0; kk < bk; kk++) {
                    s += (int32_t)qa[i * bk + kk];
                }
                row_sums[i] = s;
            }

            for (int nt = 0; nt < N; nt += block_size) {
                int bn = block_size;
                if (nt + bn > N) bn = N - nt;

                /* Select mode for B-tile and quantize */
                int mode_b = select_tile_mode(B + kt * N + nt, bk, bn, N);
                float sb, zpb = 0.0f;

                if (mode_b == 0) {
                    quantize_symmetric(B + kt * N + nt, bk, bn, N, qb, &sb);
                    sym_count++;
                } else {
                    quantize_asymmetric(B + kt * N + nt, bk, bn, N, qb, &sb, &zpb);
                    asym_count++;
                }

                /* Always compute col sums of qb — needed whenever A-tile
                   uses asymmetric mode (zpa != 0) */
                for (int j = 0; j < bn; j++) {
                    int32_t s = 0;
                    for (int kk = 0; kk < bk; kk++) {
                        s += (int32_t)qb[kk * bn + j];
                    }
                    col_sums[j] = s;
                }

                /*
                 * Accumulate: INT8 dot product + mixed-mode correction terms.
                 *
                 * General formula (derived from expanding the product
                 * a'*b' = (qa*sa + zpa)(qb*sb + zpb) and summing over k):
                 *
                 *   result = sa*sb * sum_k(qa*qb)     ... always
                 *          + sa*zpb * sum_k(qa)        ... when zpb != 0
                 *          + zpa*sb * sum_k(qb)        ... when zpa != 0
                 *          + bk * zpa * zpb            ... when both != 0
                 *
                 * When a tile uses symmetric mode, its zero_point is 0,
                 * so the corresponding correction terms vanish naturally.
                 */
                float sa_sb = sa * sb;

                for (int i = 0; i < bm; i++) {
                    for (int j = 0; j < bn; j++) {
                        int32_t acc = 0;
                        for (int kk = 0; kk < bk; kk++) {
                            acc += (int32_t)qa[i * bk + kk] *
                                   (int32_t)qb[kk * bn + j];
                        }

                        float result = sa_sb * (float)acc;

                        /* Correction for B-tile asymmetric (zpb != 0) */
                        if (zpb != 0.0f) {
                            result += sa * zpb * (float)row_sums[i];
                        }
                        /* Correction for A-tile asymmetric (zpa != 0) */
                        if (zpa != 0.0f) {
                            result += zpa * sb * (float)col_sums[j];
                        }
                        /* Both tiles asymmetric */
                        if (zpa != 0.0f && zpb != 0.0f) {
                            result += (float)bk * zpa * zpb;
                        }

                        C[(mt + i) * N + (nt + j)] += result;
                    }
                }
            }
        }
    }

    if (stats) {
        stats[0] = sym_count;
        stats[1] = asym_count;
    }

    free(qa);
    free(qb);
    free(row_sums);
    free(col_sums);

    return 0;
}

#ifndef QMATMUL_H
#define QMATMUL_H


#include <stdint.h>

/*
 * Block-quantized INT8 matrix multiplication library.
 *
 * Provides symmetric and asymmetric quantization schemes for performing
 * tiled matrix multiplication in reduced precision.
 */

/**
 * Symmetric quantization: float32 block -> INT8.
 *
 * scale = max(|src_values|) / 127.0   (1.0 when all zeros)
 * q[i][j] = clamp(round(src[i][j] / scale), -128, 127)
 *
 * Quantized output is stored contiguously (packed row-major, stride = cols).
 *
 * @param src        Source float32 block (may be sub-block of larger matrix)
 * @param rows       Block rows
 * @param cols       Block columns
 * @param src_stride Row stride in floats (full matrix width when sub-block)
 * @param dst        Output INT8 array, rows*cols elements, packed
 * @param scale      Output: computed scale factor
 * @return 0 on success, -1 on invalid arguments
 */
int quantize_symmetric(const float *src, int rows, int cols, int src_stride,
                       int8_t *dst, float *scale);

/**
 * Symmetric dequantization: INT8 -> float32.
 *
 * dst[i][j] = src[i*cols + j] * scale
 */
int dequantize_symmetric(const int8_t *src, int rows, int cols,
                         float scale, float *dst, int dst_stride);

/**
 * Asymmetric quantization: float32 block -> INT8.
 *
 * scale      = (max(src) - min(src)) / 254.0
 * zero_point = (max(src) + min(src)) / 2.0
 * q[i][j]    = clamp(round((src[i][j] - zero_point) / scale), -127, 127)
 *
 * When all values are identical: scale=1.0, zero_point=value, all q=0.
 * Packed output with stride = cols.
 *
 * @param src        Source float32 block
 * @param rows       Block rows
 * @param cols       Block columns
 * @param src_stride Row stride in floats
 * @param dst        Output INT8, packed
 * @param scale      Output: scale factor
 * @param zero_point Output: zero point (center of value range)
 * @return 0 on success, -1 on invalid arguments
 */
int quantize_asymmetric(const float *src, int rows, int cols, int src_stride,
                        int8_t *dst, float *scale, float *zero_point);

/**
 * Asymmetric dequantization: dst[i][j] = src[i*cols+j] * scale + zero_point
 */
int dequantize_asymmetric(const int8_t *src, int rows, int cols,
                          float scale, float zero_point,
                          float *dst, int dst_stride);

/**
 * Block-quantized matrix multiplication: C = A * B
 *
 * Tiles computation along M, K, N using block_size.
 * Each sub-block is independently quantized to INT8, accumulated in INT32,
 * and dequantized back to float32. C is accumulated across K-tiles.
 *
 * Row-major layout: A[i*K+j], B[i*N+j], C[i*N+j].
 *
 * @param A          Input [M x K]
 * @param M, K       Dimensions of A
 * @param B          Input [K x N]
 * @param N          Columns of B / C
 * @param C          Output [M x N], zeroed internally
 * @param block_size Tile size for quantization
 * @param mode       0=symmetric, 1=asymmetric
 * @return 0 on success, -1 on error
 */
int quantized_matmul(const float *A, int M, int K,
                     const float *B, int N,
                     float *C, int block_size, int mode);

/**
 * Adaptive block-quantized matrix multiplication: C = A * B
 *
 * Tiles the computation as in quantized_matmul, but independently selects
 * the best quantization mode (symmetric=0, asymmetric=1) for each tile
 * based on the tile's value distribution. Correctly handles mixed-mode
 * accumulation when tiles within the same K-sweep use different modes.
 *
 * @param A          Input [M x K], row-major
 * @param M, K       Dimensions of A
 * @param B          Input [K x N], row-major
 * @param N          Columns of B / C
 * @param C          Output [M x N], zeroed internally
 * @param block_size Tile size for quantization
 * @param stats      If non-NULL, filled with [sym_count, asym_count] giving
 *                   the total number of tile quantizations that used each mode
 * @return 0 on success, -1 on error
 */
int adaptive_quantized_matmul(const float *A, int M, int K,
                              const float *B, int N,
                              float *C, int block_size,
                              int *stats);

/**
 * Reference float32 matrix multiply: C = A * B (no quantization).
 */
void reference_matmul(const float *A, int M, int K,
                      const float *B, int N, float *C);

#endif /* QMATMUL_H */

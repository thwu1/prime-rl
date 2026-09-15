#ifndef MATMUL_H
#define MATMUL_H

/*
 *
 * Single-precision General Matrix Multiplication (SGEMM)
 *
 * Computes C[M x N] = A[M x K] * B[K x N]
 *
 * All matrices stored in column-major order with leading dimension
 * equal to the row count:
 *   A[row][col] = *(A + col * M + row)
 *   B[row][col] = *(B + col * K + row)
 *   C[row][col] = *(C + col * M + row)
 */

/* Optimized implementation using AVX2/FMA intrinsics with cache blocking */
void matmul(float* A, float* B, float* C, int M, int N, int K);

/* Naive reference implementation for correctness verification */
void matmul_naive(float* A, float* B, float* C, int M, int N, int K);

#endif /* MATMUL_H */

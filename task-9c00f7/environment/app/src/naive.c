/*
 */

#include "matmul.h"

void matmul_naive(float* A, float* B, float* C, int M, int N, int K) {
    for (int i = 0; i < M; i++) {
        for (int j = 0; j < N; j++) {
            float acc = 0.0f;
            for (int p = 0; p < K; p++) {
                acc += A[p * M + i] * B[j * K + p];
            }
            C[j * M + i] = acc;
        }
    }
}

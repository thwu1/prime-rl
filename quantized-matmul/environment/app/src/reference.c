/* reference.c — Reference float32 matrix multiplication (provided) */


#include "qmatmul.h"
#include <string.h>

void reference_matmul(const float *A, int M, int K,
                      const float *B, int N, float *C) {
    memset(C, 0, (size_t)M * N * sizeof(float));
    for (int i = 0; i < M; i++) {
        for (int k = 0; k < K; k++) {
            float a_ik = A[i * K + k];
            for (int j = 0; j < N; j++) {
                C[i * N + j] += a_ik * B[k * N + j];
            }
        }
    }
}

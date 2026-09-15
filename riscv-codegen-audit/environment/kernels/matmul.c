/* Dense matrix multiply: C = A * B (N x N, single precision) */
#include <stdio.h>
#include <stdlib.h>

#define N 64

void matmul_ref(int n, const float *restrict A, const float *restrict B,
                float *restrict C) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            float s = 0.0f;
            for (int k = 0; k < n; k++) {
                s += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = s;
        }
    }
}

int main(void) {
    float *A = (float *)malloc(N * N * sizeof(float));
    float *B = (float *)malloc(N * N * sizeof(float));
    float *C = (float *)malloc(N * N * sizeof(float));
    if (!A || !B || !C) return 1;

    for (int i = 0; i < N * N; i++) {
        A[i] = (float)(i % 17) * 0.1f;
        B[i] = (float)(i % 13) * 0.1f;
    }

    matmul_ref(N, A, B, C);

    double sum = 0.0;
    for (int i = 0; i < N * N; i++) sum += (double)C[i];
    printf("MATMUL checksum: %.6f\n", sum);

    free(A);
    free(B);
    free(C);
    return 0;
}

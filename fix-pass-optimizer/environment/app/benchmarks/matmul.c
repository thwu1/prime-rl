#include <stdlib.h>

void matmul(int *A, int *B, int *C, int n) {
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            int sum = 0;
            for (int k = 0; k < n; k++) {
                sum += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = sum;
        }
    }
}

int main(void) {
    int n = 64;
    int *A = (int *)malloc(n * n * sizeof(int));
    int *B = (int *)malloc(n * n * sizeof(int));
    int *C = (int *)malloc(n * n * sizeof(int));
    for (int i = 0; i < n * n; i++) {
        A[i] = i % 17;
        B[i] = i % 13;
    }
    matmul(A, B, C, n);
    int result = 0;
    for (int i = 0; i < n * n; i++)
        result += C[i];
    free(A);
    free(B);
    free(C);
    return result % 256;
}

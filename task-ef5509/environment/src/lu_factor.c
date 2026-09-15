/*
 * Parallel in-place LU factorization (no pivoting) using OpenMP.
 * Decomposes a diagonally-dominant matrix A into L and U factors
 * stored in the same matrix.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define MAT_SIZE 100

int main() {
    double *A = (double *)malloc(MAT_SIZE * MAT_SIZE * sizeof(double));

    srand(42);
    for (int i = 0; i < MAT_SIZE; i++)
        for (int j = 0; j < MAT_SIZE; j++)
            A[i * MAT_SIZE + j] = (double)(rand() % 10) + 1.0
                                  + (i == j ? MAT_SIZE * 10.0 : 0.0);

    #pragma omp parallel for
    for (int k = 0; k < MAT_SIZE - 1; k++) {
        for (int i = k + 1; i < MAT_SIZE; i++) {
            A[i * MAT_SIZE + k] /= A[k * MAT_SIZE + k];
            for (int j = k + 1; j < MAT_SIZE; j++) {
                A[i * MAT_SIZE + j] -= A[i * MAT_SIZE + k] * A[k * MAT_SIZE + j];
            }
        }
    }

    double diag_sum = 0.0, off_sum = 0.0;
    for (int i = 0; i < MAT_SIZE; i++)
        for (int j = 0; j < MAT_SIZE; j++) {
            if (i == j)
                diag_sum += A[i * MAT_SIZE + j];
            else
                off_sum += A[i * MAT_SIZE + j];
        }
    printf("%.10f\n%.10f\n", diag_sum, off_sum);

    free(A);
    return 0;
}

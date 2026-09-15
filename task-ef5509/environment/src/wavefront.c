/*
 * Parallel 2D wavefront (dynamic programming) computation using OpenMP.
 * Each cell dp[i][j] depends on dp[i-1][j], dp[i][j-1], and dp[i-1][j-1].
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <omp.h>

#define N 200

int main() {
    int *dp = (int *)calloc(N * N, sizeof(int));

    srand(42);
    for (int i = 0; i < N; i++) {
        dp[i] = rand() % 10;
        dp[i * N] = rand() % 10;
    }

    #pragma omp parallel for collapse(2)
    for (int i = 1; i < N; i++) {
        for (int j = 1; j < N; j++) {
            dp[i * N + j] = dp[(i - 1) * N + j]
                          + dp[i * N + (j - 1)]
                          + dp[(i - 1) * N + (j - 1)];
        }
    }

    long long checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += dp[i * N + j];
    printf("%lld\n", checksum);

    free(dp);
    return 0;
}

/*
 *
 * Correctness test harness for SGEMM implementations.
 * Compares matmul() against matmul_naive() across many matrix sizes.
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include "matmul.h"

/* Deterministic PRNG (xorshift32) for reproducible test data */
static unsigned int prng_state = 0xDEADBEEFu;

static float rand_float(void) {
    prng_state ^= prng_state << 13;
    prng_state ^= prng_state >> 17;
    prng_state ^= prng_state << 5;
    return (float)(prng_state & 0x7FFFFFFFu) / (float)0x7FFFFFFFu * 2.0f - 1.0f;
}

static int test_matmul(int M, int N, int K, const char* category) {
    float* A = (float*)malloc((size_t)M * K * sizeof(float));
    float* B = (float*)malloc((size_t)K * N * sizeof(float));
    float* C_naive = (float*)calloc((size_t)M * N, sizeof(float));
    float* C_opt   = (float*)calloc((size_t)M * N, sizeof(float));

    if (!A || !B || !C_naive || !C_opt) {
        fprintf(stderr, "Allocation failed for M=%d N=%d K=%d\n", M, N, K);
        free(A); free(B); free(C_naive); free(C_opt);
        return 0;
    }

    /* Reset PRNG for each test so results are independent */
    prng_state = (unsigned int)(M * 10007 + N * 1009 + K * 101 + 42);
    for (int i = 0; i < M * K; i++) A[i] = rand_float();
    for (int i = 0; i < K * N; i++) B[i] = rand_float();

    matmul_naive(A, B, C_naive, M, N, K);
    matmul(A, B, C_opt, M, N, K);

    /* Check for NaN/Inf */
    int has_nan = 0;
    for (int i = 0; i < M * N; i++) {
        if (isnan(C_opt[i]) || isinf(C_opt[i])) {
            has_nan = 1;
            break;
        }
    }

    /* Check that result is not all zeros (implementation must compute something) */
    float sum_abs = 0.0f;
    for (int i = 0; i < M * N && i < 1000; i++) {
        sum_abs += fabsf(C_opt[i]);
    }

    /* Compute max absolute error */
    float max_err = 0.0f;
    for (int i = 0; i < M * N; i++) {
        float err = fabsf(C_naive[i] - C_opt[i]);
        if (err > max_err) max_err = err;
    }

    /* Tolerance scales with K due to floating-point accumulation order differences */
    float tol = (float)K * 2e-5f;
    if (tol < 1e-5f) tol = 1e-5f;

    int pass = !has_nan && (sum_abs > 1e-10f || (M * N == 0)) && (max_err < tol);

    printf("[%s] M=%-4d N=%-4d K=%-4d  max_err=%.8f  tol=%.8f  %s",
           category, M, N, K, max_err, tol, pass ? "PASS" : "FAIL");
    if (has_nan) printf("  (NaN/Inf detected)");
    if (sum_abs < 1e-10f && M * N > 0) printf("  (output is all zeros)");
    printf("\n");

    free(A); free(B); free(C_naive); free(C_opt);
    return pass;
}

int main(void) {
    int all_pass = 1;
    int n_pass = 0, n_total = 0;

    printf("=== SGEMM Correctness Tests ===\n\n");

    /* Aligned sizes: M multiple of 16, N multiple of 6 */
    int aligned[][3] = {
        {16, 6, 8},
        {32, 12, 16},
        {64, 24, 32},
        {128, 96, 64},
        {256, 192, 128},
        {512, 384, 256},
    };
    for (int t = 0; t < (int)(sizeof(aligned)/sizeof(aligned[0])); t++) {
        int r = test_matmul(aligned[t][0], aligned[t][1], aligned[t][2], "aligned  ");
        if (!r) all_pass = 0; else n_pass++;
        n_total++;
    }

    /* Non-aligned sizes (edge cases for masking/padding) */
    int unaligned[][3] = {
        {17, 7, 9},
        {33, 11, 15},
        {100, 200, 300},
        {127, 63, 255},
        {513, 257, 129},
        {47, 19, 83},
        {255, 1, 100},
        {1, 255, 100},
    };
    for (int t = 0; t < (int)(sizeof(unaligned)/sizeof(unaligned[0])); t++) {
        int r = test_matmul(unaligned[t][0], unaligned[t][1], unaligned[t][2], "unaligned");
        if (!r) all_pass = 0; else n_pass++;
        n_total++;
    }

    /* Small/degenerate sizes */
    int small[][3] = {
        {1, 1, 1},
        {3, 5, 7},
        {8, 4, 2},
        {15, 5, 10},
        {2, 3, 500},
    };
    for (int t = 0; t < (int)(sizeof(small)/sizeof(small[0])); t++) {
        int r = test_matmul(small[t][0], small[t][1], small[t][2], "small    ");
        if (!r) all_pass = 0; else n_pass++;
        n_total++;
    }

    /* Large size */
    {
        int r = test_matmul(1000, 1000, 1000, "large    ");
        if (!r) all_pass = 0; else n_pass++;
        n_total++;
    }

    printf("\n=== Results: %d/%d passed ===\n", n_pass, n_total);
    printf("\n%s\n", all_pass ? "ALL_TESTS_PASSED" : "SOME_TESTS_FAILED");

    return all_pass ? 0 : 1;
}

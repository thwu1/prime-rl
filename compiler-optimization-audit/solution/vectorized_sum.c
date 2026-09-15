/*
 * Vectorized sum_floats using AVX intrinsics.
 *
 * The original scalar reduction loop in target.c cannot be auto-vectorized
 * by GCC at -O3 -mavx2 without -ffast-math, because floating-point
 * addition is not associative under IEEE 754. This implementation uses
 * explicit AVX intrinsics to perform 8-wide packed additions, with a
 * scalar tail loop for remaining elements.
 *
 */
#include <immintrin.h>

float sum_floats(const float *arr, int n) {
    int i = 0;
    __m256 vsum = _mm256_setzero_ps();

    /* Process 8 floats at a time using AVX packed addition */
    for (; i + 8 <= n; i += 8) {
        __m256 chunk = _mm256_loadu_ps(arr + i);
        vsum = _mm256_add_ps(vsum, chunk);
    }

    /* Horizontal reduction: 8-wide -> scalar */
    __m128 hi  = _mm256_extractf128_ps(vsum, 1);
    __m128 lo  = _mm256_castps256_ps128(vsum);
    __m128 s4  = _mm_add_ps(lo, hi);
    s4 = _mm_hadd_ps(s4, s4);
    s4 = _mm_hadd_ps(s4, s4);
    float result = _mm_cvtss_f32(s4);

    /* Scalar tail for remaining elements */
    for (; i < n; i++) {
        result += arr[i];
    }

    return result;
}

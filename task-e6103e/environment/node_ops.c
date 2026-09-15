#include "node_ops.h"

int score_lower_bound(const double *arr, int n, double target) {
    int lo = 0, hi = n;
    while (lo < hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] < target)
            lo = mid + 1;
        else
            hi = mid;
    }
    return lo;
}

int score_count_in_range(const double *arr, int n, double lo, double hi) {
    if (n == 0 || lo > hi) return 0;
    int start = score_lower_bound(arr, n, lo);
    int end = score_lower_bound(arr, n, hi);
    while (end < n && arr[end] <= hi) end++;
    return (end > start) ? end - start : 0;
}

void score_merge_sorted(double *dst, const double *src1, int n1,
                        const double *src2, int n2) {
    int i = 0, j = 0, k = 0;
    while (i < n1 && j < n2) {
        if (src1[i] <= src2[j])
            dst[k++] = src1[i++];
        else
            dst[k++] = src2[j++];
    }
    while (i < n1) dst[k++] = src1[i++];
    while (j < n2) dst[k++] = src2[j++];
}

uint32_t node_ops_checksum(uint32_t seed) {
    uint32_t h = seed;
    h ^= h >> 16;
    h *= 0x45d9f3bu;
    h ^= h >> 16;
    h *= 0x45d9f3bu;
    h ^= h >> 16;
    return h;
}

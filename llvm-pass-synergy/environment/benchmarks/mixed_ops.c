/* Benchmark: mixed optimization opportunities (inline, const prop, diverse patterns) */
#include <stdint.h>

static int abs_val(int x) { return x < 0 ? -x : x; }
static int max_val(int a, int b) { return a > b ? a : b; }
static int min_val(int a, int b) { return a < b ? a : b; }
static int clamp(int x, int lo, int hi) { return min_val(max_val(x, lo), hi); }

uint32_t rotate_left(uint32_t v, int s) {
    return (v << s) | (v >> (32 - s));
}

uint32_t hash_mix(uint32_t a, uint32_t b, uint32_t c) {
    a -= b; a -= c; a ^= (c >> 13);
    b -= c; b -= a; b ^= (a << 8);
    c -= a; c -= b; c ^= (b >> 13);
    a -= b; a -= c; a ^= (c >> 12);
    b -= c; b -= a; b ^= (a << 16);
    c -= a; c -= b; c ^= (b >> 5);
    a -= b; a -= c; a ^= (c >> 3);
    b -= c; b -= a; b ^= (a << 10);
    c -= a; c -= b; c ^= (b >> 15);
    return c;
}

void clamp_array(int *arr, int n, int lo, int hi) {
    for (int i = 0; i < n; i++) {
        arr[i] = clamp(arr[i], lo, hi);
    }
}

int manhattan_distance(int *xs, int *ys, int n) {
    int dist = 0;
    for (int i = 1; i < n; i++) {
        dist += abs_val(xs[i] - xs[i-1]) + abs_val(ys[i] - ys[i-1]);
    }
    return dist;
}

void feistel_round(uint32_t *left, uint32_t *right, uint32_t key) {
    uint32_t temp = *right;
    uint32_t f = rotate_left(*right ^ key, 7);
    f += rotate_left(*right & key, 11);
    f ^= rotate_left(*right | key, 13);
    *right = *left ^ f;
    *left = temp;
}

void encrypt_block(uint32_t *data, const uint32_t *keys, int rounds) {
    uint32_t left = data[0], right = data[1];
    for (int i = 0; i < rounds; i++) {
        feistel_round(&left, &right, keys[i]);
    }
    data[0] = left;
    data[1] = right;
}

int weighted_median_approx(int *vals, int *weights, int n) {
    int total_weight = 0;
    for (int i = 0; i < n; i++) total_weight += weights[i];
    int half = total_weight / 2;
    int cumulative = 0;
    for (int i = 0; i < n; i++) {
        cumulative += weights[i];
        if (cumulative >= half) return vals[i];
    }
    return vals[n - 1];
}

void block_process(uint32_t *data, int nblocks, const uint32_t *keys, int rounds) {
    for (int i = 0; i < nblocks; i++) {
        encrypt_block(&data[i * 2], keys, rounds);
    }
}

int range_sum(int *prefix, int l, int r) {
    if (l == 0) return prefix[r];
    return prefix[r] - prefix[l - 1];
}

int count_in_range(int *arr, int n, int lo, int hi) {
    int count = 0;
    for (int i = 0; i < n; i++) {
        if (arr[i] >= lo && arr[i] <= hi) count++;
    }
    return count;
}

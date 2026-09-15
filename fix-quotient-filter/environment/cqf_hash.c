#include "cqf_hash.h"
#include <string.h>

void cqf_hash(const char *item, int q_bits, int r_bits, uint32_t seed,
              int *quotient, int *remainder) {
    /* FNV-1a 64-bit, seeded by XOR with seed */
    uint64_t h = UINT64_C(14695981039346656037) ^ (uint64_t)seed;
    size_t len = strlen(item);
    for (size_t i = 0; i < len; i++) {
        h ^= (uint8_t)item[i];
        h *= UINT64_C(1099511628211);
    }

    /* splitmix64 finalizer for avalanche */
    h ^= h >> 30;
    h *= UINT64_C(0xbf58476d1ce4e5b9);
    h ^= h >> 27;
    h *= UINT64_C(0x94d049bb133111eb);
    h ^= h >> 31;

    int total_bits = q_bits + r_bits;
    uint64_t fp = h & ((UINT64_C(1) << total_bits) - 1);
    *quotient  = (int)(fp >> r_bits);
    *remainder = (int)(fp & ((UINT64_C(1) << r_bits) - 1));
}

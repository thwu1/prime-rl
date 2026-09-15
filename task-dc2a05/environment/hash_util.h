#pragma once


// MurmurHash3 64-bit integer finalizer.
// This is a bijection on uint64_t, providing excellent avalanche properties.
// Used to compute probe starting positions from keys.

#include <cstdint>

inline uint64_t murmurHash3_64(uint64_t h) {
    h ^= h >> 33;
    h *= 0xff51afd7ed558ccdULL;
    h ^= h >> 33;
    h *= 0xc4ceb9fe1a85ec53ULL;
    h ^= h >> 33;
    return h;
}

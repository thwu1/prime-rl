/*
 * PtrHash Minimal Perfect Hash Function — header and hash primitives.
 *
 */

#ifndef PTRHASH_H
#define PTRHASH_H

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/* Hash constants and primitives (provided — do not modify)           */
/* ------------------------------------------------------------------ */

#define PTRHASH_FX_C 0x517cc1b727220a95ULL

/*
 * FxHash for 64-bit integer keys.
 * h(k) = k * C, where C is an odd constant.
 * This is a bijection on uint64_t, so distinct keys always produce
 * distinct hash values.
 */
static inline uint64_t fx_hash(uint64_t key) {
    return key * PTRHASH_FX_C;
}

/*
 * Hash an 8-bit pilot value with a 64-bit seed.
 * Returns a 64-bit perturbation value.
 */
static inline uint64_t hash_pilot(uint8_t pilot, uint64_t seed) {
    return PTRHASH_FX_C * ((uint64_t)pilot ^ seed);
}

/*
 * Bijective 64-bit finalizer (murmur3 fmix64).
 * Thoroughly mixes all input bits so that the output's high bits
 * depend on every input bit.
 */
static inline uint64_t fmix64(uint64_t k) {
    k ^= k >> 33;
    k *= 0xff51afd7ed558ccdULL;
    k ^= k >> 33;
    k *= 0xc4ceb9fe1a85ec53ULL;
    k ^= k >> 33;
    return k;
}

/*
 * Multiply-shift reduction: maps a 64-bit value x uniformly to [0, m).
 * Computes floor(x * m / 2^64) using 128-bit arithmetic.
 */
static inline uint64_t reduce64(uint64_t x, uint64_t m) {
    return (uint64_t)((__uint128_t)x * (__uint128_t)m >> 64);
}

/*
 * 32-bit variant: maps a 32-bit value x uniformly to [0, m).
 * Computes floor(x * m / 2^32).
 */
static inline uint32_t reduce32(uint32_t x, uint32_t m) {
    return (uint32_t)((uint64_t)x * (uint64_t)m >> 32);
}

/* ------------------------------------------------------------------ */
/* PtrHash API                                                        */
/* ------------------------------------------------------------------ */

/*
 * Opaque handle to a constructed MPHF.
 */
typedef struct PtrHash PtrHash;

/*
 * Build a minimal perfect hash function from the given key set.
 *
 * Parameters:
 *   keys — array of n distinct uint64_t keys (not modified)
 *   n    — number of keys (may be 0)
 *
 * Returns a valid PtrHash pointer on success, or NULL if construction
 * fails to converge.  The caller must free the result with ptrhash_free().
 */
PtrHash *ptrhash_build(const uint64_t *keys, size_t n);

/*
 * Query the MPHF.  Returns the unique index in {0, ..., n-1} for the
 * given key.
 *
 * Precondition: key must be a member of the original build set.
 * Behaviour is undefined for keys not in the build set.
 */
size_t ptrhash_query(const PtrHash *ph, uint64_t key);

/*
 * Free all resources associated with the MPHF.
 * Passing NULL is a no-op.
 */
void ptrhash_free(PtrHash *ph);

#endif /* PTRHASH_H */

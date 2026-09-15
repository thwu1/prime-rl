#include "bitpool.h"
#include <stdlib.h>

struct bitpool_t {
    uint64_t state;
    int count;
};

/* SplitMix64 hash to decorrelate consecutive seeds */
static uint64_t splitmix64(uint64_t x) {
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static uint64_t xorshift64(uint64_t *s) {
    *s ^= *s << 13;
    *s ^= *s >> 7;
    *s ^= *s << 17;
    return *s;
}

static uint64_t init_state(uint64_t seed) {
    uint64_t s = splitmix64(seed ? seed : 0x12345678ABCDEF01ULL);
    return s ? s : 1; /* xorshift64 must not have zero state */
}

bitpool_t *bitpool_create(uint64_t seed) {
    bitpool_t *pool = (bitpool_t *)malloc(sizeof(bitpool_t));
    if (!pool) return NULL;
    pool->state = init_state(seed);
    pool->count = 0;
    return pool;
}

void bitpool_free(bitpool_t *pool) {
    if (pool) free(pool);
}

int bitpool_get_bit(bitpool_t *pool) {
    pool->count++;
    return (int)(xorshift64(&pool->state) & 1);
}

int bitpool_bits_used(bitpool_t *pool) {
    return pool->count;
}

void bitpool_reset(bitpool_t *pool, uint64_t seed) {
    pool->state = init_state(seed);
    pool->count = 0;
}

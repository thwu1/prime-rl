/*
 * CacheLineEF: compressed storage for sorted integer sequences.
 *
 * Packs groups of values into 64-byte cache-line-aligned blocks
 * with O(1) random-access decoding.
 *
 */

#ifndef CACHELINE_EF_H
#define CACHELINE_EF_H

#include <stdint.h>
#include <stddef.h>

#define CLEF_CHUNK_SIZE 44

typedef struct __attribute__((aligned(64))) {
    uint32_t offset;
    uint8_t  high_bits[16];
    uint8_t  low_bits[CLEF_CHUNK_SIZE];
} CacheLineEFBlock;

typedef struct {
    CacheLineEFBlock *blocks;
    size_t num_blocks;
    size_t num_values;
} CacheLineEF;

/*
 * Build from a non-decreasing sequence of uint64_t values.
 * Returns 0 on success, -1 on error.
 * On success, ef->blocks must be freed with cacheline_ef_free().
 */
int cacheline_ef_build(CacheLineEF *ef, const uint64_t *values, size_t n);

/*
 * Decode the value at the given index (0-indexed).
 * Precondition: index < ef->num_values.
 */
uint64_t cacheline_ef_query(const CacheLineEF *ef, size_t index);

/*
 * Free heap memory owned by the structure.
 */
void cacheline_ef_free(CacheLineEF *ef);

/*
 * Total size in bytes of the encoded blocks.
 */
size_t cacheline_ef_size_bytes(const CacheLineEF *ef);

#endif /* CACHELINE_EF_H */

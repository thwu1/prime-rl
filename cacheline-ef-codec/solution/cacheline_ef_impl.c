/*
 * CacheLineEF: Per-Cacheline Elias-Fano Encoding — reference implementation.
 *
 */

#include "cacheline_ef.h"
#include <stdlib.h>
#include <string.h>

/* ---- select helpers ---- */

/* Find the position of the r-th set bit (0-indexed) in a 64-bit word. */
static inline int select64(uint64_t word, int r) {
    for (int i = 0; i < r; i++) {
        word &= word - 1;          /* clear lowest set bit */
    }
    return __builtin_ctzll(word);   /* position of next set bit */
}

/*
 * select128: find the r-th set bit (0-indexed) in the 128-bit bitvector
 * stored as 16 bytes in little-endian order.
 */
static inline int select128(const uint8_t *bits, int r) {
    uint64_t lo, hi;
    memcpy(&lo, bits, 8);
    memcpy(&hi, bits + 8, 8);

    int lo_count = __builtin_popcountll(lo);
    if (r < lo_count) {
        return select64(lo, r);
    }
    return 64 + select64(hi, r - lo_count);
}

/* ---- public API ---- */

int cacheline_ef_build(CacheLineEF *ef, const uint64_t *values, size_t n) {
    if (!ef) return -1;

    if (n == 0) {
        ef->blocks     = NULL;
        ef->num_blocks = 0;
        ef->num_values = 0;
        return 0;
    }

    /* Verify non-decreasing order */
    for (size_t i = 1; i < n; i++) {
        if (values[i] < values[i - 1]) return -1;
    }

    size_t num_blocks = (n + CLEF_CHUNK_SIZE - 1) / CLEF_CHUNK_SIZE;

    /* 64-byte aligned allocation */
    size_t alloc_size = num_blocks * sizeof(CacheLineEFBlock);
    void *mem = aligned_alloc(64, alloc_size);
    if (!mem) return -1;

    ef->blocks     = (CacheLineEFBlock *)mem;
    ef->num_blocks = num_blocks;
    ef->num_values = n;

    for (size_t b = 0; b < num_blocks; b++) {
        size_t start = b * CLEF_CHUNK_SIZE;
        size_t count = (start + CLEF_CHUNK_SIZE <= n)
                       ? (size_t)CLEF_CHUNK_SIZE
                       : (n - start);

        CacheLineEFBlock *blk = &ef->blocks[b];
        memset(blk, 0, sizeof(CacheLineEFBlock));

        uint32_t offset = (uint32_t)(values[start] >> 8);
        blk->offset = offset;

        for (size_t i = 0; i < count; i++) {
            uint64_t v = values[start + i];
            uint32_t rel_high = (uint32_t)(v >> 8) - offset;
            uint32_t bit_pos  = rel_high + (uint32_t)i;

            if (bit_pos >= 128) {
                free(ef->blocks);
                ef->blocks = NULL;
                return -1;
            }

            blk->high_bits[bit_pos / 8] |= (uint8_t)(1U << (bit_pos % 8));
            blk->low_bits[i] = (uint8_t)(v & 0xFF);
        }
    }

    return 0;
}

uint64_t cacheline_ef_query(const CacheLineEF *ef, size_t index) {
    size_t block_idx = index / CLEF_CHUNK_SIZE;
    size_t local_idx = index % CLEF_CHUNK_SIZE;

    const CacheLineEFBlock *blk = &ef->blocks[block_idx];

    uint32_t offset = blk->offset;
    uint8_t  low    = blk->low_bits[local_idx];

    int bit_pos       = select128(blk->high_bits, (int)local_idx);
    uint32_t rel_high = (uint32_t)bit_pos - (uint32_t)local_idx;

    return ((uint64_t)(offset + rel_high) << 8) | (uint64_t)low;
}

void cacheline_ef_free(CacheLineEF *ef) {
    if (ef && ef->blocks) {
        free(ef->blocks);
        ef->blocks = NULL;
    }
    if (ef) {
        ef->num_blocks = 0;
        ef->num_values = 0;
    }
}

size_t cacheline_ef_size_bytes(const CacheLineEF *ef) {
    return ef->num_blocks * 64;
}

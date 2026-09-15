#ifndef CACHESIM_H
#define CACHESIM_H

#include <stdint.h>

/*
 * Native LRU cache simulator library.
 * Provides a C implementation of LRU replacement for cross-validation
 * with the Python simulator.
 */

typedef struct {
    uint64_t tag;
    uint64_t last_access;
    int valid;
} csim_block_t;

typedef struct {
    int num_sets;
    int num_ways;
    int block_size;
    csim_block_t *blocks;
    uint64_t clock;
    uint64_t hits;
    uint64_t misses;
} csim_cache_t;

/* Create a new LRU cache simulator */
csim_cache_t* csim_create(int num_sets, int num_ways, int block_size);

/* Process a single memory access. Returns 1 for hit, 0 for miss. */
int csim_access(csim_cache_t *cache, uint64_t addr);

/* Free all resources */
void csim_destroy(csim_cache_t *cache);

#endif

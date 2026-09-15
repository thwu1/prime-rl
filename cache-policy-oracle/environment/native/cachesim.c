#include "cachesim.h"
#include <stdlib.h>
#include <string.h>

csim_cache_t* csim_create(int num_sets, int num_ways, int block_size) {
    csim_cache_t *cache = (csim_cache_t *)malloc(sizeof(csim_cache_t));
    if (!cache) return NULL;

    cache->num_sets = num_sets;
    cache->num_ways = num_ways;
    cache->block_size = block_size;
    cache->blocks = (csim_block_t *)calloc(num_sets * num_ways,
                                            sizeof(csim_block_t));
    cache->clock = 0;
    cache->hits = 0;
    cache->misses = 0;

    return cache;
}

int csim_access(csim_cache_t *cache, uint64_t addr) {
    uint64_t tag = addr / cache->block_size;
    int set_idx = (int)(tag % cache->num_sets);
    int base = set_idx * cache->num_ways;

    cache->clock++;

    /* Check for hit */
    for (int w = 0; w < cache->num_ways; w++) {
        if (cache->blocks[base + w].valid &&
            cache->blocks[base + w].tag == tag) {
            cache->blocks[base + w].last_access = cache->clock;
            cache->hits++;
            return 1;
        }
    }

    /* Miss */
    cache->misses++;

    /* Find victim: first invalid way, or LRU (minimum last_access) */
    int victim = 0;
    uint64_t min_time = UINT64_MAX;
    for (int w = 0; w < cache->num_ways; w++) {
        if (!cache->blocks[base + w].valid) {
            victim = w;
            goto do_insert;
        }
        if (cache->blocks[base + w].last_access < min_time) {
            min_time = cache->blocks[base + w].last_access;
            victim = w;
        }
    }

do_insert:
    cache->blocks[base + victim].tag = tag;
    cache->blocks[base + victim].valid = 1;

    return 0;
}

void csim_destroy(csim_cache_t *cache) {
    if (cache) {
        if (cache->blocks) free(cache->blocks);
        free(cache);
    }
}

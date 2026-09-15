/*
 * cache.c - Cache simulator core implementation.
 *
 * Supports configurable capacity, block size, and associativity.
 * Uses true LRU replacement and write-back / write-allocate policy.
 */

#include <stdlib.h>
#include <math.h>
#include "cache.h"

Cache *cache_create(int capacity, int block_size, int associativity) {
    Cache *c = malloc(sizeof(Cache));
    c->capacity = capacity;
    c->block_size = block_size;
    c->associativity = associativity;
    c->n_sets = capacity / (block_size * associativity);
    c->n_offset_bits = (int)log2((double)block_size);
    c->n_index_bits = c->n_sets > 1 ? (int)log2((double)c->n_sets) : 0;

    c->lines = malloc((size_t)c->n_sets * sizeof(CacheLine *));
    for (int i = 0; i < c->n_sets; i++) {
        c->lines[i] = calloc((size_t)associativity, sizeof(CacheLine));
    }

    c->hits = 0;
    c->misses = 0;
    c->writebacks = 0;
    c->n_stores = 0;
    c->n_loads = 0;
    c->time = 0;
    return c;
}

void cache_destroy(Cache *c) {
    for (int i = 0; i < c->n_sets; i++) {
        free(c->lines[i]);
    }
    free(c->lines);
    free(c);
}

static unsigned int get_tag(Cache *c, unsigned int addr) {
    return addr >> (c->n_offset_bits + c->n_index_bits + 1);
}

static unsigned int get_index(Cache *c, unsigned int addr) {
    if (c->n_index_bits == 0)
        return 0;
    return (addr >> c->n_offset_bits) & ((1u << c->n_index_bits) - 1);
}

int cache_access(Cache *c, char op, unsigned int addr) {
    c->time++;
    unsigned int tag = get_tag(c, addr);
    unsigned int idx = get_index(c, addr);
    int is_write = (op == 'w');

    if (is_write)
        c->n_stores++;
    else
        c->n_loads++;

    CacheLine *set = c->lines[idx];

    /* Check for hit */
    for (int w = 0; w < c->associativity; w++) {
        if (set[w].valid && set[w].tag == tag) {
            c->hits++;
            if (is_write)
                set[w].dirty = 1;
            return 1;
        }
    }

    /* Miss */
    c->misses++;

    /* Find victim: first invalid way, else LRU */
    int vw = -1;
    for (int w = 0; w < c->associativity; w++) {
        if (!set[w].valid) {
            vw = w;
            break;
        }
    }
    if (vw < 0) {
        unsigned long oldest = set[0].last_used;
        vw = 0;
        for (int w = 1; w < c->associativity; w++) {
            if (set[w].last_used < oldest) {
                oldest = set[w].last_used;
                vw = w;
            }
        }
    }

    /* Writeback dirty victim */
    if (set[vw].valid && set[vw].dirty)
        c->writebacks++;

    /* Install new line */
    set[vw].valid = 1;
    set[vw].tag = tag;
    set[vw].dirty = 0;
    set[vw].last_used = c->time;
    return 0;
}

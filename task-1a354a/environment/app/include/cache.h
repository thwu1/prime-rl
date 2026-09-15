/*
 */
#ifndef CACHE_H
#define CACHE_H

#include "types.h"

typedef struct {
    uint64_t tag;
    LineState state;
    uint64_t last_access;   /* monotonic counter for LRU ordering */
    int valid;              /* 1 if this way holds data, 0 otherwise */
} CacheLine;

typedef struct {
    CacheLine *lines;       /* array of size 'associativity' */
    int associativity;
} CacheSet;

typedef struct {
    CacheSet *sets;
    int num_sets;
    int associativity;
    int block_bits;         /* log2(block_size) */
    int set_bits;           /* log2(num_sets) */
    /* per-processor access statistics */
    int reads;
    int writes;
    int read_hits;
    int read_misses;
    int write_hits;
    int write_misses;
} Cache;

/* Lifecycle */
void  cache_init(Cache *c, int num_sets, int associativity, int block_size);
void  cache_free(Cache *c);

/* Address decomposition */
int      cache_set_index(Cache *c, uint64_t addr);
uint64_t cache_tag(Cache *c, uint64_t addr);

/* Lookup: returns way index if tag is present and valid, -1 on miss */
int cache_lookup(Cache *c, int set_idx, uint64_t tag);

/* Returns the way index of the LRU candidate (prefers invalid ways) */
int cache_find_lru(Cache *c, int set_idx);

/* Update the LRU timestamp of a line */
void cache_touch(Cache *c, int set_idx, int way, uint64_t cycle);

/* Install a line into set_idx/way with given tag, state and timestamp */
void cache_install(Cache *c, int set_idx, int way, uint64_t tag,
                   LineState state, uint64_t cycle);

/* State accessors */
LineState cache_get_state(Cache *c, int set_idx, int way);
void      cache_set_state(Cache *c, int set_idx, int way, LineState state);

/* Returns 1 if way holds valid data */
int cache_line_valid(Cache *c, int set_idx, int way);

#endif /* CACHE_H */

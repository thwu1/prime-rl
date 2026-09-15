/*
 */
#include <stdlib.h>
#include <string.h>
#include "cache.h"

static int ilog2(int n) {
    int r = 0;
    while (n > 1) { n >>= 1; r++; }
    return r;
}

void cache_init(Cache *c, int num_sets, int associativity, int block_size) {
    c->num_sets      = num_sets;
    c->associativity = associativity;
    c->block_bits    = ilog2(block_size);
    c->set_bits      = ilog2(num_sets);

    c->reads = c->writes = 0;
    c->read_hits = c->read_misses = 0;
    c->write_hits = c->write_misses = 0;

    c->sets = (CacheSet *)malloc(num_sets * sizeof(CacheSet));
    for (int i = 0; i < num_sets; i++) {
        c->sets[i].associativity = associativity;
        c->sets[i].lines = (CacheLine *)calloc(associativity, sizeof(CacheLine));
        for (int j = 0; j < associativity; j++) {
            c->sets[i].lines[j].state       = STATE_INVALID;
            c->sets[i].lines[j].valid       = 0;
            c->sets[i].lines[j].last_access = 0;
            c->sets[i].lines[j].tag         = 0;
        }
    }
}

void cache_free(Cache *c) {
    for (int i = 0; i < c->num_sets; i++)
        free(c->sets[i].lines);
    free(c->sets);
}

int cache_set_index(Cache *c, uint64_t addr) {
    return (int)((addr >> c->block_bits) & (uint64_t)(c->num_sets - 1));
}

uint64_t cache_tag(Cache *c, uint64_t addr) {
    return addr >> (c->block_bits + c->set_bits);
}

int cache_lookup(Cache *c, int set_idx, uint64_t tag) {
    CacheSet *set = &c->sets[set_idx];
    for (int i = 0; i < c->associativity; i++) {
        if (set->lines[i].valid &&
            set->lines[i].tag == tag &&
            set->lines[i].state != STATE_INVALID) {
            return i;
        }
    }
    return -1;
}

int cache_find_lru(Cache *c, int set_idx) {
    CacheSet *set = &c->sets[set_idx];

    /* prefer an invalid / empty way */
    for (int i = 0; i < c->associativity; i++) {
        if (!set->lines[i].valid || set->lines[i].state == STATE_INVALID)
            return i;
    }

    /* all ways valid — return the one with the smallest last_access */
    int lru = 0;
    uint64_t oldest = set->lines[0].last_access;
    for (int i = 1; i < c->associativity; i++) {
        if (set->lines[i].last_access < oldest) {
            oldest = set->lines[i].last_access;
            lru = i;
        }
    }
    return lru;
}

void cache_touch(Cache *c, int set_idx, int way, uint64_t cycle) {
    c->sets[set_idx].lines[way].last_access = cycle;
}

void cache_install(Cache *c, int set_idx, int way,
                   uint64_t tag, LineState state, uint64_t cycle) {
    CacheLine *l  = &c->sets[set_idx].lines[way];
    l->tag         = tag;
    l->state       = state;
    l->valid       = 1;
    l->last_access = cycle;
}

LineState cache_get_state(Cache *c, int set_idx, int way) {
    return c->sets[set_idx].lines[way].state;
}

void cache_set_state(Cache *c, int set_idx, int way, LineState state) {
    c->sets[set_idx].lines[way].state = state;
    if (state == STATE_INVALID)
        c->sets[set_idx].lines[way].valid = 0;
}

int cache_line_valid(Cache *c, int set_idx, int way) {
    return c->sets[set_idx].lines[way].valid &&
           c->sets[set_idx].lines[way].state != STATE_INVALID;
}

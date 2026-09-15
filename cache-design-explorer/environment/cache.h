#ifndef CACHE_H
#define CACHE_H

typedef struct {
    int valid;
    int dirty;
    unsigned int tag;
    unsigned long last_used;
} CacheLine;

typedef struct {
    int capacity;
    int block_size;
    int associativity;
    int n_sets;
    int n_offset_bits;
    int n_index_bits;
    CacheLine **lines;
    int hits;
    int misses;
    int writebacks;
    int n_stores;
    int n_loads;
    unsigned long time;
} Cache;

Cache *cache_create(int capacity, int block_size, int associativity);
void cache_destroy(Cache *cache);
int cache_access(Cache *cache, char op, unsigned int addr);

#endif

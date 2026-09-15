/*
 * cache_core.c — Cache simulation core
 *
 * Simulates an N-way set-associative cache processing a memory access trace.
 * Outputs statistics as key=value pairs to stdout.
 *
 * Usage: ./cache_core <trace_file> <cache_size> <block_size> <associativity>
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_WAYS 16
#define MAX_SETS 8192

typedef struct {
    unsigned int tag;
    int valid;
    int dirty;
} CacheLine;

typedef struct {
    CacheLine ways[MAX_WAYS];
    int lru_stack[MAX_WAYS];   /* lru_stack[0] = MRU way index */
    int num_valid;
} CacheSet;

typedef struct {
    CacheSet *sets;
    int num_sets;
    int block_size;
    int associativity;
    int offset_bits;
    int index_bits;
    int total;
    int loads;
    int stores;
    int hits;
    int misses;
    int writebacks;
} Cache;

static int log2i(int n) {
    int b = 0;
    while (n > 1) { n >>= 1; b++; }
    return b;
}

Cache *cache_create(int cache_size, int block_size, int assoc) {
    Cache *c = (Cache *)calloc(1, sizeof(Cache));
    c->block_size = block_size;
    c->associativity = assoc;
    c->num_sets = cache_size / (block_size * assoc);
    c->offset_bits = log2i(block_size);
    c->index_bits = log2i(c->num_sets);
    c->sets = (CacheSet *)calloc(c->num_sets, sizeof(CacheSet));
    for (int i = 0; i < c->num_sets; i++) {
        for (int j = 0; j < assoc; j++) {
            c->sets[i].lru_stack[j] = j;
        }
    }
    return c;
}

static int get_set_index(Cache *c, unsigned int addr) {
    unsigned int block_num = addr >> c->offset_bits;
    if (c->num_sets <= 1)
        return 0;
    return block_num % (c->num_sets - 1);
}

static unsigned int get_tag(Cache *c, unsigned int addr) {
    return addr >> (c->offset_bits + c->index_bits);
}

static void promote_lru(CacheSet *set, int assoc, int way) {
    int pos = -1;
    for (int i = 0; i < assoc; i++) {
        if (set->lru_stack[i] == way) { pos = i; break; }
    }
    if (pos <= 0) return;
    int w = set->lru_stack[pos];
    for (int i = pos; i > 0; i--) {
        set->lru_stack[i] = set->lru_stack[i - 1];
    }
    set->lru_stack[0] = w;
}

void cache_access(Cache *c, char op, unsigned int addr) {
    c->total++;
    if (op == 'r') c->loads++;
    else c->stores++;

    int si = get_set_index(c, addr);
    unsigned int tag = get_tag(c, addr);
    CacheSet *set = &c->sets[si];

    for (int w = 0; w < c->associativity; w++) {
        if (set->ways[w].valid && set->ways[w].tag == tag) {
            c->hits++;
            promote_lru(set, c->associativity, w);
            return;
        }
    }

    c->misses++;

    int victim = -1;
    for (int w = 0; w < c->associativity; w++) {
        if (!set->ways[w].valid) {
            victim = w;
            break;
        }
    }
    if (victim < 0) {
        victim = set->lru_stack[c->associativity - 1];
        if (set->ways[victim].dirty) {
            c->writebacks++;
        }
    }

    set->ways[victim].valid = 1;
    set->ways[victim].tag = tag;
    set->ways[victim].dirty = (op == 'w');
    promote_lru(set, c->associativity, victim);
}

void cache_destroy(Cache *c) {
    free(c->sets);
    free(c);
}

int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <trace> <cache_size> <block_size> <assoc>\n",
                argv[0]);
        return 1;
    }

    const char *trace_path = argv[1];
    int cache_size = atoi(argv[2]);
    int block_size = atoi(argv[3]);
    int assoc = atoi(argv[4]);

    Cache *c = cache_create(cache_size, block_size, assoc);

    FILE *f = fopen(trace_path, "r");
    if (!f) {
        fprintf(stderr, "Error: cannot open %s\n", trace_path);
        cache_destroy(c);
        return 1;
    }

    char op;
    unsigned int addr;
    while (fscanf(f, " %c %x", &op, &addr) == 2) {
        cache_access(c, op, addr);
    }
    fclose(f);

    printf("total_accesses=%d\n", c->total);
    printf("loads=%d\n", c->loads);
    printf("stores=%d\n", c->stores);
    printf("hits=%d\n", c->hits);
    printf("misses=%d\n", c->misses);
    printf("writebacks=%d\n", c->writebacks);
    printf("bytes_bus_to_cache=%d\n", c->misses * c->block_size);
    printf("bytes_cache_to_bus=%d\n", c->writebacks * c->block_size);
    printf("bytes_total_traffic=%d\n",
           (c->misses + c->writebacks) * c->block_size);

    cache_destroy(c);
    return 0;
}

/*
 * cachesim.c - Cache simulator driver.
 *
 * Usage: ./cachesim <trace_file> <capacity> <block_size> <associativity>
 *
 * Reads a memory access trace and simulates cache behavior, printing
 * statistics including hit/miss counts, rates, and traffic metrics.
 */

#include <stdio.h>
#include <stdlib.h>
#include "cache.h"

static void run_trace(Cache *cache, const char *path) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        perror(path);
        exit(1);
    }
    char op;
    unsigned int addr;
    while (fscanf(fp, " %c %x", &op, &addr) == 2) {
        cache_access(cache, op, addr);
    }
    fclose(fp);
}

static void print_stats(Cache *c) {
    int total = c->hits + c->misses;
    double hit_rate = total > 0 ? (double)c->hits / total * 100.0 : 0.0;
    double miss_rate = total > 0 ? (double)c->misses / total * 100.0 : 0.0;
    int bus_to_cache = c->misses * c->block_size;
    int cache_to_bus_wb = c->writebacks * c->block_size;
    int total_traffic_wb = bus_to_cache + cache_to_bus_wb;
    int cache_to_bus_wt = c->n_stores * c->block_size;
    int total_traffic_wt = bus_to_cache + cache_to_bus_wt;

    printf("hits %d\n", c->hits);
    printf("misses %d\n", c->misses);
    printf("writebacks %d\n", c->writebacks);
    printf("hit_rate %.2f\n", hit_rate);
    printf("miss_rate %.2f\n", miss_rate);
    printf("n_stores %d\n", c->n_stores);
    printf("bus_to_cache %d\n", bus_to_cache);
    printf("cache_to_bus_wb %d\n", cache_to_bus_wb);
    printf("total_traffic_wb %d\n", total_traffic_wb);
    printf("cache_to_bus_wt %d\n", cache_to_bus_wt);
    printf("total_traffic_wt %d\n", total_traffic_wt);
}

int main(int argc, char *argv[]) {
    if (argc != 5) {
        fprintf(stderr,
                "Usage: %s <trace> <capacity> <block_size> <associativity>\n",
                argv[0]);
        return 1;
    }
    const char *trace = argv[1];
    int capacity = atoi(argv[2]);
    int block_size = atoi(argv[3]);
    int assoc = atoi(argv[4]);

    Cache *cache = cache_create(capacity, block_size, assoc);
    run_trace(cache, trace);
    print_stats(cache);
    cache_destroy(cache);
    return 0;
}

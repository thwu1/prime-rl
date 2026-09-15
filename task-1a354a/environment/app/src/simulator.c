/*
 */
#include <stdio.h>
#include <stdlib.h>
#include "simulator.h"

void simulator_init(Simulator *sim, int num_procs,
                    int num_sets, int associativity, int block_size) {
    sim->num_procs = num_procs;
    sim->cycle     = 0;
    sim->bus_rd    = 0;
    sim->bus_rdx   = 0;
    sim->bus_upgr  = 0;
    sim->flushes   = 0;

    sim->caches = (Cache *)malloc(num_procs * sizeof(Cache));
    for (int i = 0; i < num_procs; i++)
        cache_init(&sim->caches[i], num_sets, associativity, block_size);
}

void simulator_free(Simulator *sim) {
    for (int i = 0; i < sim->num_procs; i++)
        cache_free(&sim->caches[i]);
    free(sim->caches);
}

void simulator_print_stats(Simulator *sim) {
    for (int i = 0; i < sim->num_procs; i++) {
        Cache *c = &sim->caches[i];
        printf("PROCESSOR %d\n", i);
        printf("  reads: %d\n",        c->reads);
        printf("  writes: %d\n",       c->writes);
        printf("  read_hits: %d\n",    c->read_hits);
        printf("  read_misses: %d\n",  c->read_misses);
        printf("  write_hits: %d\n",   c->write_hits);
        printf("  write_misses: %d\n", c->write_misses);
    }
    printf("BUS\n");
    printf("  bus_rd: %d\n",   sim->bus_rd);
    printf("  bus_rdx: %d\n",  sim->bus_rdx);
    printf("  bus_upgr: %d\n", sim->bus_upgr);
    printf("  flushes: %d\n",  sim->flushes);
}

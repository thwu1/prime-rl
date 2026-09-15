/*
 *
 * MESI Cache Coherence Protocol — IMPLEMENT THIS FILE
 *
 * Complete the process_access() function to simulate the MESI snooping
 * bus protocol for a system of processors with private write-back,
 * write-allocate, set-associative LRU caches.
 *
 * Use the cache API from cache.h for all cache operations.
 * Update the statistics counters in both the per-processor Cache struct
 * and the Simulator bus counters.
 */
#include "simulator.h"

void process_access(Simulator *sim, int proc_id, char op, uint64_t addr) {
    (void)sim; (void)proc_id; (void)op; (void)addr;
    /* TODO: implement MESI protocol logic */
}

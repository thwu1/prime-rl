/*
 */
#ifndef SIMULATOR_H
#define SIMULATOR_H

#include "cache.h"

typedef struct {
    Cache    *caches;       /* array of per-processor caches */
    int       num_procs;
    uint64_t  cycle;        /* monotonic counter for LRU ordering */

    /* bus transaction counters */
    int bus_rd;             /* BusRd:  read request on read miss */
    int bus_rdx;            /* BusRdX: read-exclusive on write miss */
    int bus_upgr;           /* BusUpgr: upgrade Shared->Modified */
    int flushes;            /* Flush:  write-back of dirty data */
} Simulator;

/* Lifecycle */
void simulator_init(Simulator *sim, int num_procs,
                    int num_sets, int associativity, int block_size);
void simulator_free(Simulator *sim);

/* Output */
void simulator_print_stats(Simulator *sim);

/*
 * Process a single memory access.  Called once per trace line.
 * Defined in protocol.c — this is the function you must implement.
 *
 *   proc_id : processor issuing the access (0 .. num_procs-1)
 *   op      : 'R' for read, 'W' for write
 *   addr    : byte address
 */
void process_access(Simulator *sim, int proc_id, char op, uint64_t addr);

#endif /* SIMULATOR_H */
